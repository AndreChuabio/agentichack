import Link from "next/link";
import type { Metadata } from "next";
import { PublicFooter, SUPPORT_EMAIL } from "@/components/PublicFooter";

export const metadata: Metadata = {
  title: "Refund policy | Merit",
  description:
    "The refund terms for the one-time $99 dossier purchase, stated plainly.",
};

/**
 * Refund policy for the single paid product. Card networks require the
 * refund terms to be disclosed before purchase, so the Track paywall links
 * here next to the buy button.
 */
export default function RefundsPage() {
  return (
    <div className="flex flex-1 flex-col px-5 py-10">
      <header className="mx-auto w-full max-w-3xl">
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

      <main className="mx-auto w-full max-w-3xl py-8">
        <div className="rounded-2xl border border-black/5 bg-surface p-8 shadow-[0_4px_24px_-8px_rgba(31,26,46,0.12)]">
          <h1 className="font-display text-3xl font-bold tracking-tight text-ink">
            Refund policy
          </h1>
          <p className="mt-2 text-sm text-muted">
            Merit has one paid product. Here is exactly how refunds on it
            work. Effective 13 August 2026.
          </p>

          <div className="mt-8 flex flex-col gap-8 text-sm leading-relaxed text-ink">
            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                The free tier
              </h2>
              <p className="text-muted">
                The evidence ledger and per-criterion narratives are free.
                There is nothing to refund.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                The $99 dossier: 14-day money back
              </h2>
              <p className="text-muted">
                The attorney-ready dossier PDF is a one-time $99 purchase. If
                it does not work for you, for any reason, email us within 14
                days of purchase and you get a full refund. No forms, no
                argument. Refunds go back to your original payment method and
                typically settle within 5 to 10 business days, depending on
                your bank.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                How to request one
              </h2>
              <p className="text-muted">
                Email{" "}
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  {SUPPORT_EMAIL}
                </a>{" "}
                from the email address on your Merit account and say you want
                a refund. That is the whole process. If something went wrong
                with the purchase itself, for example you paid and the dossier
                did not unlock, email the same address and we will fix it
                first and refund you if we cannot.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Before you dispute a charge
              </h2>
              <p className="text-muted">
                A card dispute takes weeks and costs everyone fees. Emailing
                us takes minutes and ends in the same full refund. Please try
                us first.
              </p>
            </section>
          </div>
        </div>
      </main>

      <PublicFooter />
    </div>
  );
}
