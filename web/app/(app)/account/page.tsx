"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useUser } from "@/lib/useUser";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardTitle, CardDescription } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";

/**
 * Account page: the two data-subject rights the privacy policy promises.
 * Export downloads everything Merit stores about the caller as JSON;
 * delete removes the account and cascades to every per-user table.
 */
export default function AccountPage() {
  const router = useRouter();
  const { user, signOut } = useUser();

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const [confirmText, setConfirmText] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const data = await api.account.export();
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "merit-data-export.json";
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError((e as Error).message);
    } finally {
      setExporting(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    setDeleteError(null);
    try {
      await api.account.remove();
      await signOut();
      router.replace("/");
    } catch (e) {
      setDeleteError((e as Error).message);
      setDeleting(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8">
      <header className="flex flex-col gap-2">
        <Badge tone="primary">Your account</Badge>
        <h1 className="font-display text-3xl font-bold tracking-tight text-ink">
          Your data, your call
        </h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted">
          {user?.email ? `Signed in as ${user.email}. ` : ""}
          Everything Merit stores about you can be exported or deleted from
          here, exactly as the privacy policy promises.
        </p>
      </header>

      <Card>
        <CardTitle>Export your data</CardTitle>
        <CardDescription>
          Download every row Merit holds for your account as a single JSON
          file: profile, evidence, outreach log, and generated-artifact
          metadata.
        </CardDescription>
        <div className="mt-4 flex items-center gap-3">
          <Button
            variant="secondary"
            onClick={handleExport}
            disabled={exporting}
          >
            {exporting ? (
              <>
                <Spinner size={16} /> Preparing export
              </>
            ) : (
              "Download my data (JSON)"
            )}
          </Button>
        </div>
        {exportError ? (
          <p className="mt-3 rounded-2xl bg-danger/10 px-4 py-2.5 text-sm text-danger">
            {exportError}
          </p>
        ) : null}
      </Card>

      <Card className="border-danger/20">
        <CardTitle>Delete your account</CardTitle>
        <CardDescription>
          Permanently deletes your account and every row keyed to it:
          profile, evidence, narratives, outreach history, artifacts, and
          purchases. This cannot be undone, and it does not automatically
          refund a dossier purchase. If you want a refund too, request it
          first via the refund policy.
        </CardDescription>
        <div className="mt-4 flex max-w-sm flex-col gap-3">
          <Input
            label='Type "delete my account" to confirm'
            name="confirm-delete"
            value={confirmText}
            onChange={(e) => setConfirmText(e.target.value)}
            placeholder="delete my account"
            autoComplete="off"
          />
          <div>
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={
                deleting || confirmText.trim().toLowerCase() !== "delete my account"
              }
            >
              {deleting ? (
                <>
                  <Spinner size={16} /> Deleting account
                </>
              ) : (
                "Delete my account permanently"
              )}
            </Button>
          </div>
        </div>
        {deleteError ? (
          <p className="mt-3 rounded-2xl bg-danger/10 px-4 py-2.5 text-sm text-danger">
            {deleteError}
          </p>
        ) : null}
      </Card>
    </div>
  );
}
