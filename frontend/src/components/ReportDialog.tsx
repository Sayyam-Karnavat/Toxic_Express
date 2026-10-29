import { useState } from "react";
import { toast } from "sonner";

import { safetyApi } from "@/api/admin";
import { useMeta } from "@/api/meta";
import { errorMessage } from "@/lib/api";
import type { EntityType, ReportReason } from "@/types";

import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";
import { Label, Textarea } from "./ui/input";

const LABELS: Record<string, string> = {
  harassment: "Harassment or bullying",
  hate: "Hate speech",
  threat: "Threats or violence",
  doxxing: "Shares someone's personal info",
  self_harm: "Someone may be at risk",
  sexual: "Sexual content",
  spam: "Spam",
  other: "Something else",
};

export function ReportDialog({
  open,
  onOpenChange,
  entityType,
  entityId,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  entityType: EntityType;
  entityId: string;
}) {
  const { data: meta } = useMeta();
  const [reason, setReason] = useState<ReportReason>("harassment");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await safetyApi.report(entityType, entityId, reason, note);
      toast.success("Thanks. Our moderators will take a look.");
      onOpenChange(false);
      setNote("");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Report" description="Reports are anonymous. Venting is allowed; harming people isn't.">
        <fieldset className="space-y-xs">
          <legend className="sr-only">Reason</legend>
          {(meta?.report_reasons ?? (Object.keys(LABELS) as ReportReason[])).map((r) => (
            <label key={r} className="flex min-h-11 cursor-pointer items-center gap-sm rounded-sm px-sm hover:bg-surface-indigo">
              <input
                type="radio"
                name="reason"
                value={r}
                checked={reason === r}
                onChange={() => setReason(r)}
                className="accent-primary"
              />
              {LABELS[r] ?? r}
            </label>
          ))}
        </fieldset>
        <div className="mt-md">
          <Label htmlFor="report-note">Anything else? (optional)</Label>
          <Textarea id="report-note" maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />
        </div>
        <div className="mt-xl flex justify-end gap-sm">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy}>
            Send report
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
