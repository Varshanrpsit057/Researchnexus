import { redirect } from "next/navigation";

// The research graph lives at /workspace/[id]/graph now; old links still land there.
export default async function LegacyWorkspaceGraph({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/graph`);
}
