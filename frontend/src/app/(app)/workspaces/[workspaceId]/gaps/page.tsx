import { redirect } from "next/navigation";

// Research gaps live at /workspace/[id]/gaps now; old links still land there.
export default async function LegacyWorkspaceGaps({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/gaps`);
}
