import { redirect } from "next/navigation";

/** The workspace overview now lives at /workspace/[id]; this route only
 * forwards there so old links and bookmarks keep working. The section
 * pages under /workspaces/[workspaceId]/... are unaffected. */
export default async function LegacyWorkspaceOverview({ params }: { params: Promise<{ workspaceId: string }> }) {
  const { workspaceId } = await params;
  redirect(`/workspace/${workspaceId}`);
}
