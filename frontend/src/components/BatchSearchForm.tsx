import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";

// A plain GET <form>, not a client-side submit handler: the browser itself turns these fields
// into ?drug=...&batch=... on /batches/search, so the search works with no JavaScript at all,
// is a real bookmarkable/shareable URL, and needs no 'use client' boundary.
export function BatchSearchForm() {
  return (
    <form action="/batches/search" className="space-y-4" aria-label="Medicine batch checker">
      <div className="space-y-1">
        <label htmlFor="drug" className="text-sm font-medium">
          Medicine name
        </label>
        <Input
          id="drug"
          name="drug"
          required
          minLength={3}
          maxLength={120}
          placeholder="e.g. Paracetamol"
        />
      </div>
      <div className="space-y-1">
        <label htmlFor="batch" className="text-sm font-medium">
          Batch number
        </label>
        <Input
          id="batch"
          name="batch"
          required
          maxLength={60}
          placeholder="printed on the strip or box"
        />
      </div>
      <Button type="submit" className="w-full sm:w-auto">
        Check this batch
      </Button>
    </form>
  );
}
