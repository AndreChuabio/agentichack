"use client";

import { useState, useSyncExternalStore } from "react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { hasLlmKey, noLlmKey, setLlmKey, subscribeLlmKey } from "@/lib/llmKey";

/**
 * Where a user supplies their own Vercel AI Gateway key.
 *
 * Productize reads whole repositories, and a bundle is capped at 600K tokens,
 * so this surface runs on the caller's key rather than Merit's -- a rush of
 * users on ours would be a bill with no ceiling. Everything else in Merit falls
 * back to our key and is capped instead, which is why this field lives here and
 * not in a global settings screen: it is the one place it is actually required.
 *
 * The key never leaves the browser except as the X-LLM-Key header on requests
 * to the Merit API. Nothing stores it server-side.
 */
export function LlmKeyField() {
  const [value, setValue] = useState("");

  // Subscribed rather than copied into state inside an effect. The server
  // snapshot is false because localStorage does not exist there, and the client
  // corrects it on hydration; this also re-renders if the key changes in
  // another tab-driven code path.
  const hasKey = useSyncExternalStore(subscribeLlmKey, hasLlmKey, noLlmKey);

  function save() {
    setLlmKey(value);
    // Never keep the secret in component state once it is stored.
    setValue("");
  }

  function clear() {
    setLlmKey("");
    setValue("");
  }

  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-slate-200 px-4 py-4">
      <div>
        <p className="text-sm font-semibold">Your AI Gateway key</p>
        <p className="text-sm text-slate-600">
          Productize reads an entire repository, so it runs on your own key
          rather than ours. Get one at vercel.com/dashboard/ai-gateway. It stays
          in this browser and is never stored on our servers.
        </p>
      </div>

      {hasKey ? (
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-sm text-green-700">A key is set in this browser.</span>
          <Button type="button" variant="secondary" onClick={clear}>
            Remove it
          </Button>
        </div>
      ) : (
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-[16rem] flex-1">
            <Input
              name="llm_key"
              label="Vercel AI Gateway key"
              type="password"
              autoComplete="off"
              placeholder="vck_..."
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
          </div>
          <Button type="button" onClick={save} disabled={!value.trim()}>
            Save key
          </Button>
        </div>
      )}

    </div>
  );
}
