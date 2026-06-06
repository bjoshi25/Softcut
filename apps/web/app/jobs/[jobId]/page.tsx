import Link from "next/link";
import { JobView } from "../../../components/job-view";

interface Props {
  params: {
    jobId: string;
  };
}

export default function JobDetailsPage({ params }: Props) {
  const jobId = decodeURIComponent(params.jobId);
  return (
    <main className="container stack">
      <header className="panel">
        <h1>Job {jobId}</h1>
        <Link href="/">Back to pipeline</Link>
      </header>
      <JobView jobId={jobId} />
    </main>
  );
}
