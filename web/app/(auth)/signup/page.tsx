"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

export default function SignupPage() {
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }

    setSubmitting(true);

    const supabase = createClient();
    const { data, error: signUpError } = await supabase.auth.signUp({
      email: email.trim(),
      password,
    });

    if (signUpError) {
      setError(signUpError.message);
      setSubmitting(false);
      return;
    }

    // Auto-confirm is on, so signUp returns an active session. If for some
    // reason a session was not created, fall back to the login page.
    if (!data.session) {
      router.replace("/login");
      return;
    }

    router.replace("/productize");
    router.refresh();
  }

  return (
    <Card>
      <CardTitle>Create your account</CardTitle>
      <CardDescription>
        Any real email works. You will be signed in right away.
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
          autoComplete="new-password"
          placeholder="At least 6 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={6}
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
              Creating account
            </>
          ) : (
            "Create account"
          )}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link
          href="/login"
          className="font-display font-semibold text-primary hover:text-accent-pink"
        >
          Sign in
        </Link>
      </p>

      <p className="mt-2 text-center text-xs text-muted">
        By creating an account you agree to our{" "}
        <Link
          href="/terms"
          className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          terms
        </Link>{" "}
        and{" "}
        <Link
          href="/privacy"
          className="font-medium text-muted underline-offset-2 hover:text-ink hover:underline"
        >
          privacy policy
        </Link>
        .
      </p>
    </Card>
  );
}
