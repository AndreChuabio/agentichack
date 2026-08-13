import { notFound } from "next/navigation";
import { createClient } from "@/lib/supabase/server";

interface PublicSitePageProps {
  params: Promise<{ slug: string }>;
}

/**
 * The one column this route reads.
 *
 * `live_html`, never `html`. `html` is the working draft and changes on every
 * rebuild; `live_html` changes only when the user takes the publish action, so
 * reading it here is what stops a rebuild from silently replacing the page a
 * visitor is looking at.
 */
interface PublishedSiteRow {
  live_html: string;
}

/**
 * A published portfolio site, served to anyone.
 *
 * This route reads through the ordinary Supabase client rather than any
 * service-role path on purpose: the RLS policy on published_site exposes only
 * rows where published is true, so a draft returns no row here and 404s. That
 * makes the draft boundary a database rule rather than a convention this
 * component could forget.
 *
 * The stored HTML is injected directly. It is safe for the same reason the v1
 * zip was: every value in it passed through site_render._e (html.escape with
 * quote=True) at generation time, hrefs were validated as http(s), and the
 * model never emits markup -- it returns prose and two enum values. This is
 * the only place in the app that renders stored HTML, so that guarantee is
 * restated here rather than assumed.
 */
export default async function PublicSitePage({ params }: PublicSitePageProps) {
  const { slug } = await params;
  const supabase = await createClient();
  const { data } = await supabase
    .from("published_site")
    .select("live_html")
    .eq("slug", slug)
    .maybeSingle<PublishedSiteRow>();

  if (!data?.live_html) {
    notFound();
  }

  return <div dangerouslySetInnerHTML={{ __html: data.live_html }} />;
}
