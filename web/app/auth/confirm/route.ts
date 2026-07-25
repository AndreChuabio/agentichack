import { type EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";
import { createClient } from "@/lib/supabase/server";

/**
 * Server-side confirmation for emailed auth links (currently password recovery).
 *
 * The reset email points here with either a token_hash (the recommended,
 * device-independent flow) or a PKCE code. Verifying on the server writes the
 * session to cookies so the browser can then call updateUser. Unlike a
 * client-only PKCE exchange -- whose code_verifier lives in the localStorage of
 * the device that requested the reset -- a token_hash link verifies from any
 * device, so opening the email on a phone after requesting on a laptop works.
 */

// Only same-origin relative paths may be the post-verify destination, so a
// crafted ?next= cannot turn this endpoint into an open redirect. Backslashes
// are rejected because browsers normalise them to forward slashes ("/\host" ->
// "//host" -> a protocol-relative external URL).
function safeNext(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.includes("\\")) {
    return "/reset-password";
  }
  return next;
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const tokenHash = searchParams.get("token_hash");
  const type = searchParams.get("type") as EmailOtpType | null;
  const code = searchParams.get("code");
  const next = safeNext(searchParams.get("next"));

  const destination = request.nextUrl.clone();
  destination.pathname = next;
  destination.search = "";

  const supabase = await createClient();

  if (tokenHash && type) {
    const { error } = await supabase.auth.verifyOtp({ type, token_hash: tokenHash });
    if (!error) {
      destination.searchParams.set("verified", "1");
      return NextResponse.redirect(destination);
    }
  } else if (code) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) {
      destination.searchParams.set("verified", "1");
      return NextResponse.redirect(destination);
    }
  }

  // Expired, already used, wrong-device, or malformed link.
  destination.searchParams.set("error", "link");
  return NextResponse.redirect(destination);
}
