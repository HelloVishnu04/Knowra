import WorkspaceEditor from '@/components/workspace-editor';

export default async function EditCodePage({ searchParams }: { searchParams: Promise<{ repository?: string }> }) {
  const { repository = '' } = await searchParams;
  return <WorkspaceEditor key={repository} repositoryId={repository} />;
}
