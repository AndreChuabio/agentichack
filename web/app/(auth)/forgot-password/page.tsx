"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import Link from "next/link";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    const supabase = createClient();
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(
      email.trim(),
      {
        redirectTo: `${window.location.origin}/auth/confirm?next=/reset-password`,
      },
    );

    setSubmitting(false);

    if (resetError) {
      // Keep the response uniform: never surface the raw provider error (it can
      // differ by rate-limit state) and never confirm whether an account exists.
      setError(
        "We could not send a reset email right now. Please try again in a moment.",
      );
      return;
    }

    setSent(true);
  }

  if (sent) {
    return (
      <Card>
        <CardTitle>Check your email</CardTitle>
        <CardDescription>
          If an account exists for {email.trim()}, we sent a link to reset
          your password.
        </CardDescription>
        <p className="mt-6 text-center text-sm text-muted">
          <Link
            href="/login"
            className="font-display font-semibold text-primary hover:text-accent-pink"
          >
            Back to sign in
          </Link>
        </p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Reset your password</CardTitle>
      <CardDescription>
        Enter your email and we will send you a link to reset your password.
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

        {error ? (
          <p className="rounded-2xl bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </p>
        ) : null}

        <Button type="submit" size="lg" disabled={submitting} className="mt-1">
          {submitting ? (
            <>
              <Spinner size={18} className="border-white/40 border-t-white" />
              Sending
            </>
          ) : (
            "Send reset link"
          )}
        </Button>
      </form>

      <p className="mt-6 text-center text-sm text-muted">
        Remembered it?{" "}
        <Link
          href="/login"
          className="font-display font-semibold text-primary hover:text-accent-pink"
        >
          Back to sign in
        </Link>
      </p>
    </Card>
  );
}
