import type { SVGProps } from "react";

export type IconName =
  | "arrow-left"
  | "arrow-right"
  | "bookmark"
  | "building"
  | "check"
  | "chevron-down"
  | "close"
  | "document"
  | "home"
  | "logout"
  | "search"
  | "send"
  | "spark"
  | "user";

interface IconProps extends SVGProps<SVGSVGElement> {
  name: IconName;
  size?: number;
}

export function Icon({ name, size = 20, ...props }: IconProps) {
  const common = {
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
  };

  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      {...props}
      {...common}
    >
      {name === "arrow-left" && <path d="m14.5 5-7 7 7 7M8 12h11" />}
      {name === "arrow-right" && <path d="m9.5 5 7 7-7 7M16 12H5" />}
      {name === "bookmark" && <path d="M6.5 4.8A1.8 1.8 0 0 1 8.3 3h7.4a1.8 1.8 0 0 1 1.8 1.8V21L12 17.5 6.5 21V4.8Z" />}
      {name === "building" && (
        <>
          <path d="M4 21V6.5L12 3v18M20 21V9l-8-2.5" />
          <path d="M8 9h.01M8 13h.01M8 17h.01M16 12h.01M16 16h.01M2.5 21h19" />
        </>
      )}
      {name === "check" && <path d="m5 12.5 4.2 4L19 7" />}
      {name === "chevron-down" && <path d="m6 9 6 6 6-6" />}
      {name === "close" && <path d="m6 6 12 12M18 6 6 18" />}
      {name === "document" && (
        <>
          <path d="M6 3h8l4 4v14H6z" />
          <path d="M14 3v5h4M9 12h6M9 16h6" />
        </>
      )}
      {name === "home" && (
        <>
          <path d="m3 11 9-8 9 8" />
          <path d="M5.5 9.5V21h13V9.5M9.5 21v-7h5v7" />
        </>
      )}
      {name === "logout" && (
        <>
          <path d="M10 5H5v14h5M14 8l4 4-4 4M8 12h10" />
        </>
      )}
      {name === "search" && (
        <>
          <circle cx="10.5" cy="10.5" r="6.5" />
          <path d="m15.5 15.5 4.5 4.5" />
        </>
      )}
      {name === "send" && <path d="m4 4 17 8-17 8 3-8-3-8Zm3 8h14" />}
      {name === "spark" && <path d="m12 2 1.8 6.2L20 10l-6.2 1.8L12 18l-1.8-6.2L4 10l6.2-1.8L12 2Zm6 14 .7 2.3L21 19l-2.3.7L18 22l-.7-2.3L15 19l2.3-.7L18 16Z" />}
      {name === "user" && (
        <>
          <circle cx="12" cy="8" r="4" />
          <path d="M4.5 21a7.5 7.5 0 0 1 15 0" />
        </>
      )}
    </svg>
  );
}
