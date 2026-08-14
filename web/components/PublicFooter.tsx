import Link from "next/link";

export const SUPPORT_EMAIL = "andre102599@gmail.com";

const LINK_CLASS =
  "font-medium text-muted underline-offset-2 hover:text-ink hover:underline";

/**
 * Footer for the public (logged-out) surfaces: landing, auth, and legal
 * pages. The authenticated AppShell renders its own footer with the same
 * links, so every page a visitor or customer can reach carries the legal
 * surface and a working support contact.
 */
export function PublicFooter() {
  return (
    <footer className="border-t border-black/5 px-5 py-6">
      <div className="mx-auto flex w-full max-w-5xl flex-wrap items-center justify-between gap-3 text-xs text-muted">
        <span>Merit is a document preparation tool, not a law firm.</span>
        <nav className="flex flex-wrap items-center gap-4">
          <Link href="/privacy" className={LINK_CLASS}>
            Privacy
          </Link>
          <Link href="/terms" className={LINK_CLASS}>
            Terms
          </Link>
          <Link href="/refunds" className={LINK_CLASS}>
            Refunds
          </Link>
          <a href={`mailto:${SUPPORT_EMAIL}`} className={LINK_CLASS}>
            Support
          </a>
        </nav>
      </div>
    </footer>
  );
}

export default PublicFooter;
