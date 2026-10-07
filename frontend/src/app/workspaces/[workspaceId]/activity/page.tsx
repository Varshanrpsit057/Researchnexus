import { redirect } from "next/navigation";

// The activity log lives at /workspace/[id]/activity now; old links still land there.
export default async function LegacyWorkspaceActivity({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/activity`);
}
