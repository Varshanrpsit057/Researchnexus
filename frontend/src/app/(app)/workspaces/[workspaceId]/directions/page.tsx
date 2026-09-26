import { redirect } from "next/navigation";

// Research directions live at /workspace/[id]/directions now; old links still land there.
export default async function LegacyWorkspaceDirections({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/directions`);
}
