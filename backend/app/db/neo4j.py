import json
from uuid import uuid4

from neo4j import GraphDatabase


class Neo4jDB:
    """Neo4j 封装。所有查询都按 novel_id 隔离；关系查询用 novel_id + character_id 双层隔离。"""

    def __init__(self, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def ping(self) -> None:
        with self._driver.session() as session:
            session.run("RETURN 1").consume()

    def ensure_constraints(self) -> None:
        """幂等创建唯一约束（Neo4j 5.x 语法）。"""
        statements = [
            "CREATE CONSTRAINT person_id IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT person_novel_name IF NOT EXISTS FOR (p:Person) REQUIRE (p.novel_id, p.name) IS UNIQUE",
        ]
        with self._driver.session() as session:
            for stmt in statements:
                session.run(stmt).consume()

    def upsert_novel(self, novel_id: str, title: str, chapters: list[dict]) -> None:
        # Neo4j 属性只允许原始类型/数组，list[dict] 需 JSON 序列化后存储
        chapters_json = json.dumps(chapters, ensure_ascii=False)
        with self._driver.session() as session:
            session.run(
                "MERGE (n:Novel {id: $novel_id}) SET n.title = $title, n.chapters = $chapters",
                novel_id=novel_id, title=title, chapters=chapters_json,
            ).consume()

    def upsert_graph(self, novel_id: str, merged) -> None:
        """merged: pipeline.merger.MergedGraph"""
        with self._driver.session() as session:
            for name, person in merged.persons.items():
                session.run(
                    """MERGE (p:Person {novel_id: $novel_id, name: $name})
                       ON CREATE SET p.id = $person_id
                       SET p.mention_count = $mention_count, p.chapters = $chapters""",
                    novel_id=novel_id, name=name, person_id=str(uuid4()),
                    mention_count=person.mention_count, chapters=sorted(person.chapters),
                ).consume()
            for (source, target, rtype), rel in merged.relationships.items():
                session.run(
                    """MATCH (a:Person {novel_id: $novel_id, name: $source})
                       MATCH (b:Person {novel_id: $novel_id, name: $target})
                       MERGE (a)-[r:RELATES_TO {novel_id: $novel_id, source: $source, target: $target, type: $type}]->(b)
                       SET r.chunk_ids = $chunk_ids, r.weight = $weight,
                           r.confidence = $confidence, r.evidence = $evidence""",
                    novel_id=novel_id, source=source, target=target, type=rtype.value,
                    chunk_ids=sorted(rel.chunk_ids), weight=rel.weight,
                    confidence=rel.confidence, evidence=json.dumps(rel.evidence, ensure_ascii=False),
                ).consume()

    def get_novel(self, novel_id: str) -> dict | None:
        with self._driver.session() as session:
            record = session.run(
                "MATCH (n:Novel {id: $novel_id}) RETURN n.title AS title, n.chapters AS chapters",
                novel_id=novel_id,
            ).single()
            if record is None:
                return None
            chapters = json.loads(record["chapters"]) if record["chapters"] else []
            return {"id": novel_id, "title": record["title"], "chapters": chapters}

    def search_characters(self, novel_id: str, q: str, limit: int = 10) -> list[dict]:
        with self._driver.session() as session:
            records = session.run(
                """MATCH (p:Person)
                   WHERE p.novel_id = $novel_id AND p.name CONTAINS $q
                   RETURN p.id AS id, p.name AS name, p.mention_count AS mention_count
                   ORDER BY p.mention_count DESC
                   LIMIT $limit""",
                novel_id=novel_id, q=q, limit=limit,
            )
            return [dict(r) for r in records]

    def get_character(self, novel_id: str, character_id: str) -> dict | None:
        with self._driver.session() as session:
            record = session.run(
                """MATCH (p:Person {id: $character_id})
                   WHERE p.novel_id = $novel_id
                   RETURN p.id AS id, p.name AS name, p.mention_count AS mention_count""",
                novel_id=novel_id, character_id=character_id,
            ).single()
            return dict(record) if record else None

    def get_subgraph(self, novel_id: str, character_id: str) -> dict | None:
        """1 跳子图（无向遍历，边保留存储方向）。novel_id + character_id 双层隔离。"""
        center = self.get_character(novel_id, character_id)
        if center is None:
            return None
        with self._driver.session() as session:
            records = list(session.run(
                """MATCH (c:Person {id: $character_id})
                   WHERE c.novel_id = $novel_id
                   MATCH (c)-[r:RELATES_TO]-(n:Person)
                   WHERE n.novel_id = $novel_id
                   RETURN n.id AS node_id, n.name AS node_name, n.mention_count AS node_mention_count,
                          r.type AS r_type, r.weight AS r_weight, r.confidence AS r_confidence,
                          r.evidence AS r_evidence,
                          startNode(r).id AS r_from_id, endNode(r).id AS r_to_id""",
                novel_id=novel_id, character_id=character_id,
            ))
        novel = self.get_novel(novel_id)
        chapter_titles = {c["id"]: c["title"] for c in (novel["chapters"] if novel else [])}
        nodes = {character_id: {**center, "is_center": True}}
        edges: list[dict] = []
        for rec in records:
            nid = rec["node_id"]
            if nid not in nodes:
                nodes[nid] = {
                    "id": nid,
                    "name": rec["node_name"],
                    "mention_count": rec["node_mention_count"],
                    "is_center": False,
                }
            evidence = []
            raw_evidence = rec["r_evidence"]
            if raw_evidence:
                raw_evidence = json.loads(raw_evidence)
            for item in raw_evidence or []:
                evidence.append({
                    "chunk_id": item["chunk_id"],
                    "chapter_id": item["chapter_id"],
                    "chapter_title": chapter_titles.get(item["chapter_id"], ""),
                    "text": item["text"],
                })
            edges.append({
                "source_id": rec["r_from_id"],
                "target_id": rec["r_to_id"],
                "type": rec["r_type"],
                "weight": rec["r_weight"],
                "confidence": rec["r_confidence"],
                "evidence": evidence,
            })
        return {"nodes": list(nodes.values()), "edges": edges}

    def count_stats(self, novel_id: str) -> dict:
        with self._driver.session() as session:
            persons = session.run(
                "MATCH (p:Person) WHERE p.novel_id = $novel_id RETURN count(p) AS c",
                novel_id=novel_id,
            ).single()["c"]
            relationships = session.run(
                "MATCH (:Person)-[r:RELATES_TO]->(:Person) WHERE r.novel_id = $novel_id RETURN count(r) AS c",
                novel_id=novel_id,
            ).single()["c"]
            return {"persons": persons, "relationships": relationships}

    def delete_novel(self, novel_id: str) -> None:
        """测试清理用：删除某小说全部节点与关系。"""
        with self._driver.session() as session:
            session.run("MATCH (p:Person) WHERE p.novel_id = $novel_id DETACH DELETE p", novel_id=novel_id).consume()
            session.run("MATCH (n:Novel) WHERE n.id = $novel_id DELETE n", novel_id=novel_id).consume()
