import { redirect } from "next/navigation";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ evaluation?: string }>;
}) {
  const { evaluation } = await searchParams;
  redirect(evaluation ? `/evaluations/${encodeURIComponent(evaluation)}` : "/assurance-center");
}
