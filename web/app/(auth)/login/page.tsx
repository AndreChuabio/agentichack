"use client";

import { Suspense, useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

function isSafeRedirect(path: string | null): path is string {
  // Same-origin relative paths only: must start with a single "/". Reject
  // protocol-relative "//host" and backslash forms like "/\host" that browsers
  // normalise to "//host" and would otherwise redirect off-site.
  return (
    typeof path === "string" &&
    path.startsWith("/") &&
    !path.startsWith("//") &&
    !path.includes("\\")
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectParam = searchParams.get("redirect");
  const destination = isSafeRedirect(redirectParam)
    ? redirectParam
    : "/productize";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const supabase = createClient();
    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    if (signInError) {
      setError(signInError.message);
      setSubmitting(false);
      return;
    }

    // Refresh so the server (proxy + layouts) sees the new session cookies,
    // then move to the protected app.
    router.replace(destination);
    router.refresh();
  }

  return (
    <Card>
      <CardTitle>Welcome back</CardTitle>
      <CardDescription>
        Sign in to keep your research on autopilot.
      </CardDescription>

      <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
        <Input
          label="Email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <Input
          label="Password"
          name="password"
          type="password"
          autoComplete="current-password"
          placeholder="Your password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />

        {error ? (
          <p className="rounded-2xl bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <Button type="submit" size="lg" disabled={submitting} className="mt-1">
          {submitting ? (
            <>
              <Spinner size={18} className="border-white/40 border-t-white" />
              Signing in
            </>
          ) : (
            "Sign in"
          )}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted">
        New here?{" "}
        <Link
          href="/signup"
          className="font-display font-semibold text-primary hover:text-accent-pink"
        >
          Create an account
        </Link>
      </p>

      <p className="mt-2 text-center text-sm text-muted">
        <Link
          href="/forgot-password"
          className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          Forgot your password?
        </Link>
      </p>
    </Card>
  );
}

export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
