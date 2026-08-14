import { PublishWizard } from "./PublishWizard";

export default function PublishPage() {
  return (
    <div className="mx-auto max-w-3xl px-5 py-10">
      <p className="text-sm font-semibold uppercase text-indigo-600">Publish</p>
      <h1 className="mt-1 text-3xl font-bold">Ship a portfolio site</h1>
      <p className="mt-2 text-slate-600">
        Merit writes the site from your profile, the repos you pick, and only
        the recognition you tick. You push it to your own GitHub Pages repo.
      </p>
      <div className="mt-8">
        <PublishWizard />
      </div>
    </div>
  );
}
