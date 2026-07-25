"use client";

import { Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createClient } from "@/lib/supabase/client";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";

// How long to wait for a recovery session before treating the link as dead, so
// an expired / invalid / wrong-device link shows an error instead of spinning
// forever.
const VERIFY_TIMEOUT_MS = 8000;

type Phase = "verifying" | "ready" | "invalid";

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // Read the recovery signals at render time. When the server confirm route
  // bounced back an error, the page starts in "invalid" without a synchronous
  // setState inside the effect (which React discourages).
  const hasLinkError = searchParams.get("error") !== null;
  const isVerified = searchParams.get("verified") === "1";
  const [phase, setPhase] = useState<Phase>(
    hasLinkError ? "invalid" : "verifying",
  );
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    // The server /auth/confirm route verifies the emailed token and redirects
    // back here with ?verified=1 (session already in cookies) or ?error on
    // failure. As a fallback, a client-exchanged PKCE link fires
    // PASSWORD_RECOVERY. We unlock the form only for one of those recovery
    // signals -- never merely because some other session already exists, so a
    // logged-in visitor cannot land here and overwrite the wrong account.
    if (hasLinkError) return;

    const supabase = createClient();
    let settled = false;
    const ready = () => {
      if (!settled) {
        settled = true;
        setPhase("ready");
      }
    };
    const invalid = () => {
      if (!settled) {
        settled = true;
        setPhase("invalid");
      }
    };

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event) => {
      if (event === "PASSWORD_RECOVERY") ready();
    });

    if (isVerified) {
      supabase.auth.getSession().then(({ data }) => {
        if (data.session) ready();
        else invalid();
      });
    }

    const timer = setTimeout(invalid, VERIFY_TIMEOUT_MS);

    return () => {
      subscription.unsubscribe();
      clearTimeout(timer);
    };
  }, [hasLinkError, isVerified]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    if (password.length < 6) {
      setError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    const supabase = createClient();
    const { error: updateError } = await supabase.auth.updateUser({ password });

    if (updateError) {
      setSubmitting(false);
      setError(updateError.message);
      return;
    }

    // Revoke every session (including any an attacker may hold from a leaked
    // token) and clear this recovery session, so the reset is a clean cutover
    // and the user signs in fresh with the new password.
    await supabase.auth.signOut({ scope: "global" });
    setSubmitting(false);
    setDone(true);
  }

  if (done) {
    return (
      <Card>
        <CardTitle>Password updated</CardTitle>
        <CardDescription>
          Your password has been changed. Sign in with it to continue.
        </CardDescription>
        <Button
          size="lg"
          className="mt-6 w-full"
          onClick={() => router.replace("/login")}
        >
          Go to sign in
        </Button>
      </Card>
    );
  }

  if (phase === "invalid") {
    return (
      <Card>
        <CardTitle>This reset link is invalid or expired</CardTitle>
        <CardDescription>
          Password reset links can only be used once and expire after a short
          time. Request a new one to continue.
        </CardDescription>
        <Button
          size="lg"
          className="mt-6 w-full"
          onClick={() => router.replace("/forgot-password")}
        >
          Request a new link
        </Button>
      </Card>
    );
  }

  if (phase === "verifying") {
    return (
      <Card>
        <CardTitle>Verifying your reset link</CardTitle>
        <CardDescription>This will only take a moment.</CardDescription>
        <div className="mt-6 flex justify-center">
          <Spinner />
        </div>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Choose a new password</CardTitle>
      <CardDescription>At least 6 characters.</CardDescription>

      <form onSubmit={handleSubmit} className="mt-6 flex flex-col gap-4">
        <Input
          label="New password"
          name="password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 6 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          minLength={6}
          required
        />
        <Input
          label="Confirm new password"
          name="confirmPassword"
          type="password"
          autoComplete="new-password"
          placeholder="Re-enter your new password"
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
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
              Updating
            </>
          ) : (
            "Update password"
          )}
        </Button>
      </form>
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense
      fallback={
        <div className="flex justify-center py-10">
          <Spinner />
        </div>
      }
    >
      <ResetPasswordForm />
    </Suspense>
  );
}
