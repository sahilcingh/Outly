import type { Metadata } from "next";
import Landing from "./landing";

export const metadata: Metadata = {
  title: "Outly · Find the opening. Write the opener.",
  description:
    "An autonomous research agent. Point it at a company or hand it a resume. Outly reads the websites, careers pages, ATS boards and job boards, then writes the email that's ready to send.",
};

export default function Page() {
  return <Landing />;
}
