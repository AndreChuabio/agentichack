import Link from "next/link";
import type { ReactNode } from "react";
import { PublicFooter } from "@/components/PublicFooter";

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-1 flex-col px-5 py-10">
      <header className="mx-auto w-full max-w-5xl">
        <Link
          href="/"
          className="inline-flex items-center gap-2 font-display text-xl font-bold tracking-tight text-ink transition-transform hover:scale-[1.03]"
        >
          <span className="grid h-8 w-8 place-items-center rounded-2xl bg-primary text-sm font-bold text-white shadow-[0_8px_20px_-8px_rgba(109,74,255,0.6)]">
            M
          </span>
          Merit
        </Link>
      </header>
      <main className="flex flex-1 items-center justify-center py-8">
        <div className="w-full max-w-md">{children}</div>
      </main>
      <PublicFooter />
    </div>
  );
}
