import { redirect } from "next/navigation";

// Citations live at /workspace/[id]/citations now; old links still land there.
export default async function LegacyWorkspaceCitations({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/citations`);
}
