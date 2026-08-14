import Link from "next/link";
import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { PublicFooter } from "@/components/PublicFooter";

/** The eight USCIS O-1A criteria, shown as the evidence Merit helps you build. */
const CRITERIA = [
  "Awards",
  "Membership",
  "Published material",
  "Judging",
  "Original contributions",
  "Scholarly articles",
  "Critical role",
  "High salary",
] as const;

/** The three surfaces, framed by the O-1A evidence each one produces. */
const PILLARS: ReadonlyArray<{
  tag: string;
  tone: "lime" | "primary" | "pink";
  title: string;
  description: string;
  builds: string;
}> = [
  {
    tag: "Track",
    tone: "lime",
    title: "Your O-1A evidence ledger",
    description:
      "Declare evidence across all eight criteria, see your coverage at a glance, draft a petition-quality narrative for each, and export an attorney-ready dossier.",
    builds: "Builds: every criterion",
  },
  {
    tag: "Productize",
    tone: "primary",
    title: "Turn your code into contributions",
    description:
      "Point Merit at a GitHub repo. It drafts a publishable paper and packages a reusable Claude plugin (skills, commands, subagents, and an MCP build plan) from the same code.",
    builds: "Builds: scholarly articles, original contributions",
  },
  {
    tag: "Market",
    tone: "pink",
    title: "Get on the record",
    description:
      "Draft sharp outreach in your voice and reach the people who get you featured, invited to judge, and recognized in your field.",
    builds: "Builds: published material, membership, critical role",
  },
];

export default async function Home() {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    redirect("/track");
  }

  return (
    <div className="flex flex-1 flex-col px-5 py-16">
      {/* Hero */}
      <section className="mx-auto w-full max-w-3xl text-center">
        <div className="mb-6 flex justify-center">
          <Badge tone="lime">Extraordinary ability, evidenced</Badge>
        </div>
        <h1 className="font-display text-5xl font-bold leading-tight tracking-tight text-ink sm:text-6xl">
          Build your <span className="text-primary">O-1A case</span>, faster
        </h1>
        <p className="mx-auto mt-5 max-w-xl text-lg text-muted">
          Merit turns your research and open-source work into O-1A evidence.
          Track all eight criteria, generate the papers and tools that count,
          and walk into your attorney hand-off with the dossier drafted.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
          <Link href="/signup">
            <Button size="lg">Start your case</Button>
          </Link>
          <Link href="/login">
            <Button variant="secondary" size="lg">
              Sign in
            </Button>
          </Link>
        </div>
      </section>

      {/* Criteria band */}
      <section className="mx-auto mt-14 w-full max-w-3xl">
        <Card className="text-center">
          <p className="text-sm font-medium text-ink">
            USCIS asks for evidence in{" "}
            <span className="font-bold text-primary">3 of 8</span> criteria to
            qualify. Merit helps you build and track them all.
          </p>
          <div className="mt-4 flex flex-wrap justify-center gap-2">
            {CRITERIA.map((c) => (
              <span
                key={c}
                className="rounded-full border border-black/10 bg-surface px-3 py-1 text-xs font-medium text-muted"
              >
                {c}
              </span>
            ))}
          </div>
        </Card>
      </section>

      {/* Pillars */}
      <section className="mx-auto mt-12 grid w-full max-w-5xl gap-5 md:grid-cols-3">
        {PILLARS.map((pillar) => (
          <Card key={pillar.tag} interactive className="flex flex-col">
            <Badge tone={pillar.tone}>{pillar.tag}</Badge>
            <CardTitle className="mt-4">{pillar.title}</CardTitle>
            <CardDescription>{pillar.description}</CardDescription>
            <p className="mt-auto pt-4 text-xs font-medium text-ink/70">
              {pillar.builds}
            </p>
          </Card>
        ))}
      </section>

      {/* Closing CTA */}
      <section className="mx-auto mt-14 w-full max-w-2xl text-center">
        <h2 className="font-display text-2xl font-bold tracking-tight text-ink">
          Start building the case for your work
        </h2>
        <p className="mx-auto mt-3 max-w-lg text-sm text-muted">
          Free to start: the evidence ledger and per-criterion narratives cost
          nothing. The attorney-ready dossier PDF is a one-time $99. Your
          evidence is private to you.
        </p>
        <div className="mt-6 flex justify-center">
          <Link href="/signup">
            <Button size="lg">Create your account</Button>
          </Link>
        </div>
      </section>

      <div className="mt-16">
        <PublicFooter />
      </div>
    </div>
  );
}
