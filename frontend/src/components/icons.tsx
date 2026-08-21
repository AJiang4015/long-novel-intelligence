/**
 * 内联 SVG monoline 图标库。
 * 路径逐字取自 design/novel-graph-workbench.html（唯一事实来源）。
 * 全部图标：viewBox="0 0 24 24"、fill="none"、stroke="currentColor"，
 * 颜色继承 currentColor，组件内不出现任何硬编码色值。
 */
import type { ReactNode, SVGProps } from "react";

export interface IconProps
  extends Omit<SVGProps<SVGSVGElement>, "width" | "height" | "strokeWidth"> {
  size?: number;
}

interface IconBaseProps extends IconProps {
  strokeWidth?: number;
  children: ReactNode;
}

function IconBase({ size = 16, strokeWidth = 1.8, children, ...rest }: IconBaseProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      aria-hidden="true"
      {...rest}
    >
      {children}
    </svg>
  );
}

/** 搜索（workbench topbar/搜索框） */
export function SearchIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </IconBase>
  );
}

/** 关闭（workbench 抽屉/详情关闭按钮） */
export function CloseIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <path d="M6 6l12 12M18 6 6 18" />
    </IconBase>
  );
}

/** 加（workbench 放大按钮） */
export function PlusIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <path d="M12 5v14M5 12h14" />
    </IconBase>
  );
}

/** 减（workbench 缩小按钮） */
export function MinusIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <path d="M5 12h14" />
    </IconBase>
  );
}

/** 适应视图（workbench 适应按钮） */
export function FitIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
    </IconBase>
  );
}

/** 文档（workbench 文件行/分析遮罩） */
export function DocIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={1.7} {...props}>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6" />
    </IconBase>
  );
}

/** 上传（workbench 拖放区） */
export function UploadIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={1.7} {...props}>
      <path d="M12 16V4m0 0 4 4m-4-4L8 8" />
      <path d="M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" />
    </IconBase>
  );
}

/** 关系图 / 人物网络（workbench 品牌图与空状态共用：三个圆 + 连线） */
export function GraphNodesIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <circle cx="6" cy="17" r="2.4" />
      <circle cx="17" cy="6" r="2.4" />
      <circle cx="17" cy="17" r="2.4" />
      <path d="M8 15.5 15 8M15.5 8.4 15.5 14.6" />
    </IconBase>
  );
}

/** 警告（design-system 错误条） */
export function WarningIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 8v5m0 3.5v.01" />
    </IconBase>
  );
}

/** 箭头（workbench 联想行「设为中心」） */
export function ArrowRightIcon(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <path d="M5 12h14m-6-6 6 6-6 6" />
    </IconBase>
  );
}

/** 品牌图（workbench topbar brand-glyph：三个圆 + 连线） */
export function BrandGlyph(props: IconProps) {
  return (
    <IconBase strokeWidth={2} {...props}>
      <circle cx="6" cy="17" r="2.4" />
      <circle cx="17" cy="6" r="2.4" />
      <circle cx="17" cy="17" r="2.4" />
      <path d="M8 15.5 15 8M15.5 8.4 15.5 14.6" />
    </IconBase>
  );
}
