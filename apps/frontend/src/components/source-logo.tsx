"use client";

import Image from "next/image";
import { useState } from "react";

export function SourceLogo({
  name,
  path,
  size = 34,
}: {
  name: string;
  path: string | null;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);

  if (!path || failed) return <span aria-hidden="true">{name.slice(0, 2)}</span>;

  return (
    <Image
      alt=""
      height={size}
      onError={() => setFailed(true)}
      src={path}
      width={size}
    />
  );
}
