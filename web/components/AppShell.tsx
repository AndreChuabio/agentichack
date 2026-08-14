"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import type { ReactNode } from "react";
import { useUser } from "@/lib/useUser";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { HelpAssistant } from "@/components/HelpAssistant";
import { SUPPORT_EMAIL } from "@/components/PublicFooter";

interface NavLink {
  href: string;
  label: string;
}

const NAV_LINKS: NavLink[] = [
  { href: "/market", label: "Market" },
  { href: "/productize", label: "Productize" },
  { href: "/track", label: "Track" },
  { href: "/publish", label: "Publish" },
  { href: "/cfp", label: "Call for Papers" },
];

export interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading, signOut } = useUser();

  const handleSignOut = async () => {
    await signOut();
    router.replace("/login");
  };

  return (
    <div className="flex min-h-full flex-col">
      <header className="sticky top-0 z-30 border-b border-black/5 bg-cream/80 backdrop-blur-md">
        <div className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-5 py-3.5">
          <Link
            href="/productize"
            className="flex items-center gap-2 font-display text-xl font-bold tracking-tight text-ink"
          >
            <span className="inline-block h-7 w-7 rounded-xl bg-primary shadow-[0_6px_18px_-6px_rgba(109,74,255,0.6)]" />
            <span>
              Me<span className="text-primary">rit</span>
            </span>
          </Link>

          <nav className="hidden items-center gap-1 sm:flex">
            {NAV_LINKS.map((link) => {
              const active =
                pathname === link.href ||
                pathname.startsWith(`${link.href}/`);
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  className={`rounded-2xl px-4 py-2 font-display text-sm font-medium transition-colors ${
                    active
                      ? "bg-primary-50 text-primary"
                      : "text-muted hover:bg-black/5 hover:text-ink"
                  }`}
                >
                  {link.label}
                </Link>
              );
            })}
          </nav>

          <div className="flex items-center gap-3">
            {loading ? (
              <Spinner size={18} />
            ) : user ? (
              <>
                <span className="hidden text-sm text-muted md:inline">
                  {user.email}
                </span>
                <Button variant="ghost" size="sm" onClick={handleSignOut}>
                  Sign out
                </Button>
              </>
            ) : (
              <Link href="/login">
                <Button variant="secondary" size="sm">
                  Sign in
                </Button>
              </Link>
            )}
          </div>
        </div>

        <nav className="flex items-center gap-1 overflow-x-auto px-5 pb-3 sm:hidden">
          {NAV_LINKS.map((link) => {
            const active =
              pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={`whitespace-nowrap rounded-2xl px-4 py-2 font-display text-sm font-medium ${
                  active
                    ? "bg-primary-50 text-primary"
                    : "text-muted hover:bg-black/5"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8">
        {children}
      </main>

      <footer className="border-t border-black/5 px-5 py-6">
        <div className="mx-auto flex w-full max-w-6xl flex-wrap items-center justify-between gap-3 text-xs text-muted">
          <span>Merit is a document preparation tool, not a law firm.</span>
          <nav className="flex flex-wrap items-center gap-4">
            <Link
              href="/privacy"
              className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Privacy
            </Link>
            <Link
              href="/terms"
              className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Terms
            </Link>
            <Link
              href="/refunds"
              className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Refunds
            </Link>
            <Link
              href="/account"
              className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Account
            </Link>
            <a
              href={`mailto:${SUPPORT_EMAIL}`}
              className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
            >
              Support
            </a>
          </nav>
        </div>
      </footer>

      <HelpAssistant />
    </div>
  );
}

export default AppShell;
