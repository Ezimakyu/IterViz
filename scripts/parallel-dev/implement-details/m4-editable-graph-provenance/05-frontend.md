# 05 — Frontend (`frontend/src/...`)

The frontend changes for M4 add inline editing to the existing
`NodeDetailsPopup`, blue-ring + `USER` badge highlighting on
`NodeCard`, and a top-left provenance-view toggle on `Graph`. The
state plumbing lives in `state/contract.ts` (Zustand) and the typed
API wrapper in `api/client.ts`.

## API client (`frontend/src/api/client.ts`)

One new wrapper:

```ts
export interface NodeUpdateRequest {
  description?: string;
  responsibilities?: string[];
  assumptions?: Assumption[];
}

export interface NodeUpdateResponse {
  node: ContractNode;
  fields_updated: string[];
  provenance_set: Record<string, string>;
}

export function updateNode(
  sessionId: string,
  nodeId: string,
  updates: NodeUpdateRequest,
) {
  return request<NodeUpdateResponse>(
    `/sessions/${sessionId}/nodes/${nodeId}`,
    { method: "PATCH", body: JSON.stringify(updates) },
  );
}
```

It uses the same `request<T>` helper as M3, so non-2xx responses
return an `ApiError` shape rather than throwing — the store can
branch on `isApiError(result)` without a try/catch.

## Store (`frontend/src/state/contract.ts`)

Two new pieces of state:

```ts
userEditedFields: Record<string, string[]>;   // nodeId -> ["description", ...]
provenanceView: boolean;
```

Three new actions:

```ts
clearUserEdits: () => void;
toggleProvenanceView: () => void;
setProvenanceView: (on: boolean) => void;
```

And the headline thunk:

```ts
updateNodeField: async (
  nodeId: string,
  field: "description" | "responsibilities" | "assumptions",
  value: string | string[] | Assumption[],
) => {
  const sid = get().sessionId;
  const contract = get().contract;
  if (!sid || !contract) return;

  const updates: NodeUpdateRequest = {};
  if (field === "description") updates.description = value as string;
  if (field === "responsibilities") updates.responsibilities = value as string[];
  if (field === "assumptions") updates.assumptions = value as Assumption[];

  set({ isLoading: true, error: null });
  const result = await API.updateNode(sid, nodeId, updates);
  if (isApiError(result)) {
    set({ isLoading: false, error: result.detail });
    return;
  }

  // Patch the node in-place. Treat the previous contract as the diff
  // baseline so the graph highlights this single edit.
  const updatedNodes = contract.nodes.map((n) =>
    n.id === nodeId ? { ...n, ...result.node } : n,
  );
  const previousFields = get().userEditedFields[nodeId] ?? [];
  const mergedFields = Array.from(
    new Set([...previousFields, ...result.fields_updated]),
  );

  set({
    previousContract: contract,
    contract: { ...contract, nodes: updatedNodes },
    isLoading: false,
    userEditedFields: {
      ...get().userEditedFields,
      [nodeId]: mergedFields,
    },
  });
},
```

Two important details:

1. **`previousContract: contract`.** This snapshots the pre-edit
   contract so the diff highlight (yellow ring + `NEW` badge from M3)
   can light up the edited node. The blue ring from M4 layers on top.
2. **`mergedFields`.** Fields edited across multiple PATCH calls
   accumulate, so even if the user edits description and then later
   responsibilities, the popup shows blue left borders on both.

`setSession` and `resetSession` both clear `userEditedFields` so that
moving between sessions never carries highlights over.

`submitAnswersAndRefine` does **not** clear `userEditedFields`. The
user's per-field ownership is a property of the live session and
should survive a refine cycle; the Architect is told about user
edits via `decided_by: user` on the contract, so the next refined
contract continues to reflect them.

## `NodeDetailsPopup` (`frontend/src/components/NodeDetailsPopup.tsx`)

The popup grew an inline edit mode for `description` and
`responsibilities` (the two fields the spec calls "free text").

State, kept in the component:

```ts
const [editingField, setEditingField] = useState<
  "description" | "responsibilities" | null
>(null);
const [draftDescription, setDraftDescription] = useState(node.description ?? "");
const [draftResponsibilities, setDraftResponsibilities] = useState(
  (node.responsibilities ?? []).join("\n"),
);

useEffect(() => {
  setDraftDescription(node.description ?? "");
  setDraftResponsibilities((node.responsibilities ?? []).join("\n"));
  setEditingField(null);
}, [node.id, node.description, node.responsibilities]);
```

The `useEffect` is the safety net for "remote update arrived while
the popup was open" — if the backend sends back a refined contract
that changes the node, the local drafts re-sync rather than fighting
the latest state.

Commit handlers:

```ts
const commitDescription = async () => {
  setEditingField(null);
  if (draftDescription === (node.description ?? "")) return;     // no-op short-circuit
  await updateNodeField(node.id, "description", draftDescription);
};

const commitResponsibilities = async () => {
  setEditingField(null);
  const next = draftResponsibilities.split("\n").map((r) => r.trim()).filter(Boolean);
  const current = node.responsibilities ?? [];
  if (next.length === current.length && next.every((v, i) => v === current[i])) {
    return;
  }
  await updateNodeField(node.id, "responsibilities", next);
};

const cancelEditing = () => {
  setEditingField(null);
  setDraftDescription(node.description ?? "");
  setDraftResponsibilities((node.responsibilities ?? []).join("\n"));
};
```

The textareas are wired up so:

- **`onBlur` → commit.** The most natural save trigger.
- **`Cmd/Ctrl+Enter` → commit.** Power-user shortcut.
- **`Esc` → cancel.** Restores the original value and closes the
  editor without firing a PATCH.

The display element is a `<p role="button" tabIndex={0}>` with an
`onClick` and `onKeyDown(Enter|Space)` to enter edit mode, so
keyboard users can edit without a mouse.

The blue left border on edited fields:

```ts
const fieldEditedClass = (edited: boolean) =>
  edited ? "border-l-2 border-blue-500 pl-2" : "";
```

The header gets a blue tinted background and a `USER-EDITED` badge
when `editedFields.length > 0 || node.decided_by === "user"`.

The footer's `decided by · …` line uses a small color rule:
`user → text-blue-300`, `prompt → text-emerald-300`, otherwise
`text-slate-400`.

Test hooks (used by `test-plan-m4.md`):

- `data-testid="node-description-{id}"` and
  `data-testid="node-edit-description-{id}"` on the text and
  textarea forms of the description.
- Same pattern for `responsibilities`.

## `NodeCard` (`frontend/src/components/NodeCard.tsx`)

The card already supported "new / changed" highlighting from M3
(yellow ring + `NEW` badge). M4 layers blue ring + `USER` badge:

```ts
const isUserEdited =
  (userEditedFields[id]?.length ?? 0) > 0 || node.decided_by === "user";
```

`isUserEdited` drives three things:

1. `!ring-blue-500/80 ring-[3px] shadow-blue-500/30` (the blue ring
   takes precedence over selection but visually composes with the
   yellow new/changed ring because they're on different sides of the
   class string).
2. A `USER` badge in the top-right of the card (only when not also
   `isNew` — the `NEW` badge wins for a brand-new node, and the user
   would just have to wait one more verify pass for their edit to
   show).
3. The `data-user-edited="true"` attribute, which is used by the
   provenance-view toggle to know which cards to dim.

Provenance view dim:

```ts
provenanceView && !isUserEdited ? "opacity-60" : "",
```

## Provenance view toggle (`frontend/src/components/Graph.tsx`)

Top-left of the graph canvas:

```tsx
<button
  type="button"
  onClick={toggleProvenanceView}
  data-testid="provenance-view-toggle"
  aria-pressed={provenanceView}
  className={`rounded border px-2 py-1 text-[11px] font-medium uppercase tracking-wide transition ${
    provenanceView
      ? "border-blue-400 bg-blue-500/20 text-blue-200"
      : "border-slate-600 bg-slate-800/70 text-slate-300 hover:border-blue-400 hover:text-blue-200"
  }`}
>
  Provenance view {provenanceView ? "on" : "off"}
</button>
```

When `provenanceView === true`, a tiny legend renders directly under
the toggle:

```
● User-edited (n)
○ Other
```

`n` is the live count of user-edited nodes — derived from
`userEditedFields` plus any node whose `decided_by === "user"`.
Toggling off restores normal opacity for every card.

The toggle does **not** call the backend, does **not** affect UVDC,
does **not** filter the QuestionPanel. It's a purely cosmetic lens
on the graph state.
