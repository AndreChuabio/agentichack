import Link from "next/link";
import type { Metadata } from "next";
import { PublicFooter, SUPPORT_EMAIL } from "@/components/PublicFooter";

export const metadata: Metadata = {
  title: "Privacy policy | Merit",
  description: "What Merit stores, what it does not, and who it is shared with.",
};

/**
 * Plain-language privacy policy. Merit stores immigration evidence for
 * users who are predominantly not US nationals, which puts GDPR in scope
 * regardless of revenue -- so this states plainly what is stored, what is
 * not (the user's API key), and who submitted content goes to.
 */
export default function PrivacyPage() {
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
            Privacy policy
          </h1>
          <p className="mt-2 text-sm text-muted">
            Merit stores immigration evidence, which is sensitive personal
            data. This page states plainly what is stored, what is not, and
            who it is shared with. No legalese padding. Effective 13 August
            2026.
          </p>

          <div className="mt-8 flex flex-col gap-8 text-sm leading-relaxed text-ink">
            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                What is stored
              </h2>
              <ul className="list-disc pl-5 text-muted marker:text-primary">
                <li>Your account email.</li>
                <li>
                  Your profile: name, title, links, and resume text.
                </li>
                <li>
                  Evidence records you add: title, description, URL, date,
                  and which USCIS criterion it supports.
                </li>
                <li>Outreach logs: who you drafted outreach to and when.</li>
                <li>
                  Generated artifacts: LaTeX, BibTeX, and plugin zips
                  produced from your evidence.
                </li>
                <li>
                  Usage traces: which model was used, token counts, cost,
                  and timestamps.
                </li>
              </ul>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                What is not stored
              </h2>
              <p className="text-muted">
                Your API key. It is held in your browser, sent with each
                request you make, used to make that one call, and never
                written to disk, a log, or a database.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Who it is shared with
              </h2>
              <p className="text-muted">
                The model providers Merit routes to via Vercel AI Gateway
                (Google, Anthropic, OpenAI) receive the content you submit
                for generation. If the optional outreach integrations are
                enabled on your deployment, the outreach content you submit
                is also sent to Senso (drafting) and Nimble (finding contacts
                and looking up public scholar profile data). These
                integrations are off unless the operator sets a Senso or
                Nimble API key; on Merit&apos;s own hosted deployment, both are
                configured. Merit does not sell your data and has no
                advertisers.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Retention and deletion
              </h2>
              <p className="text-muted">
                Your data persists until you delete your account. Deleting
                your account removes every row keyed to you.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Your rights
              </h2>
              <p className="text-muted">
                You can export your data at any time from the{" "}
                <Link
                  href="/account"
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  account page
                </Link>
                , and delete your account and all associated data from the
                same place. If anything goes wrong with either, email{" "}
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  {SUPPORT_EMAIL}
                </a>{" "}
                and we will do it by hand.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Self-hosting
              </h2>
              <p className="text-muted">
                If you run Merit yourself, none of the above involves us at
                all. The data lives in your own Supabase project, under your
                own control.
              </p>
            </section>

            <section className="flex flex-col gap-2">
              <h2 className="font-display text-lg font-semibold text-ink">
                Who we are
              </h2>
              <p className="text-muted">
                Merit is an independent software product operated by its
                founder, Andre Chuabio, in the United States, who is the data
                controller for the hosted service at meritai.me. For any
                privacy question or request, email{" "}
                <a
                  href={`mailto:${SUPPORT_EMAIL}`}
                  className="font-medium underline-offset-2 hover:text-ink hover:underline"
                >
                  {SUPPORT_EMAIL}
                </a>
                .
              </p>
            </section>
          </div>
        </div>
      </main>

      <PublicFooter />
    </div>
  );
}
