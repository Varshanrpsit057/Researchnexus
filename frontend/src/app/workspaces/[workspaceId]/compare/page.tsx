import { redirect } from "next/navigation";

// Comparison lives at /workspace/[id]/compare now; old links still land there.
export default async function LegacyWorkspaceCompare({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/compare`);
}
