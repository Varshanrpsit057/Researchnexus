import { redirect } from "next/navigation";

// Research chat lives at /workspace/[id]/chat now; old links still land there.
export default async function LegacyWorkspaceChat({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}/chat`);
}
