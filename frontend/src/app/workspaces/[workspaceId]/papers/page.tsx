import { redirect } from "next/navigation";

// A workspace's papers (with their pins, tags and notes) are on its overview now.
export default async function LegacyWorkspacePapers({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}#papers`);
}
