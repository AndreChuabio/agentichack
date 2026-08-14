import Link from "next/link";
import type { Metadata } from "next";
import { PublicFooter, SUPPORT_EMAIL } from "@/components/PublicFooter";

export const metadata: Metadata = {
  title: "Terms of service | Merit",
  description:
    "The plain-language terms that govern using Merit and buying the dossier.",
};

/**
 * Plain-language terms of service. Written in the same voice as the privacy
 * policy: state what the deal is, without legalese padding. The two load-
 * bearing sections are What Merit is (the not-a-law-firm boundary) and
 * Payments and refunds (the $99 dossier and the 14-day refund promise).
 */
export default function TermsPage() {
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
            Terms of service
          </h1>
          <p className="mt-2 text-sm text-muted">
            Plain-language terms, no legalese padding. By creating an account
            or buying anything on Merit you agree to these terms and to the{" "}
            <Link
              href="/privacy"
              className="font-medium underline-offset-2 hover:text-ink hover:underline"
            >
              privacy policy
            </Link>
            . Effective 13 August 2026.
          </p>

          <div className="mt-8 flex flex-col gap-8 text-sm leading-relaxed text-ink">
            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                What Merit is, and is not
              </h2>
              <p className="text-muted">
                Merit is software that helps you organize evidence of your
                work, track it against the USCIS O-1A criteria, and generate
                draft documents from it. Merit is a document preparation tool.
                It is not a law firm, using it does not create an
                attorney-client relationship, and nothing it produces is legal
                advice. Every document Merit generates is a draft intended for
                review by a licensed immigration attorney, and Merit makes no
                promise about the outcome of any visa petition or other
                application.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Your account and your content
              </h2>
              <p className="text-muted">
                You are responsible for your account credentials and for the
                accuracy of the evidence you add. Your evidence and the
                documents generated from it are yours. You give Merit
                permission to store and process that content solely to provide
                the service, as described in the privacy policy. Merit does
                not sell your data and has no advertisers.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Payments and refunds
              </h2>
              <p className="text-muted">
                The evidence ledger and per-criterion narratives are free. The
                attorney-ready dossier PDF is a one-time purchase of $99,
                processed by Stripe. Merit never sees your card details. If
                the dossier does not work for you, you can request a full
                refund within 14 days of purchase under our{" "}
                <Link
                  href="/refunds"
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  refund policy
                </Link>
                .
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Acceptable use
              </h2>
              <p className="text-muted">
                Do not use Merit for anything unlawful, do not submit evidence
                you know to be false, do not attempt to break or overload the
                service, and do not present Merit-generated drafts as
                attorney-reviewed work when they are not. Merit may suspend
                accounts that abuse the service.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                The service is provided as is
              </h2>
              <p className="text-muted">
                Merit uses AI models to generate drafts, and AI output can
                contain errors. Review everything before you rely on it. The
                service is provided as is, without warranties of any kind, and
                Merit does not guarantee uninterrupted availability. To the
                fullest extent permitted by law, Merit&apos;s total liability
                for any claim arising from the service is limited to the
                amount you paid Merit in the twelve months before the claim.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Ending your account
              </h2>
              <p className="text-muted">
                You can delete your account and all data keyed to it at any
                time from the{" "}
                <Link
                  href="/account"
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  account page
                </Link>
                . These terms may change as the product does; the effective
                date above is updated when they do, and material changes will
                be flagged on the site.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Who we are
              </h2>
              <p className="text-muted">
                Merit is an independent software product operated by its
                founder, Andre Chuabio, in the United States. Questions,
                refund requests, or disputes: email{" "}
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  {SUPPORT_EMAIL}
                </a>{" "}
                and we will work it out with you directly. These terms are
                governed by the laws of the United States.
              </p>
            </section>
          </div>
        </div>
      </main>

      <PublicFooter />
    </div>
  );
}
