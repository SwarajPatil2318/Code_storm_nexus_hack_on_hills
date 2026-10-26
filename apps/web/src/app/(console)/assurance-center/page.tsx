import { AssuranceCenter } from "@/components/assurance-center";
export const metadata = { title: "Assurance Center" };
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ evaluation?: string }>;
}) {
  const params = await searchParams;
  return (
    <AssuranceCenter
      initialEvaluation={typeof params.evaluation === "string" ? params.evaluation : ""}
    />
  );
}
