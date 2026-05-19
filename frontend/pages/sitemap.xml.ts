import type { GetServerSideProps } from "next";

import { buildSitemapXml, resolveSiteUrlFromRequestHeaders } from "../lib/seo";

export const getServerSideProps: GetServerSideProps = async ({ req, res }) => {
  const siteUrl = resolveSiteUrlFromRequestHeaders({
    host: req.headers.host,
    "x-forwarded-host": req.headers["x-forwarded-host"],
    "x-forwarded-proto": req.headers["x-forwarded-proto"],
  });

  res.setHeader("Content-Type", "application/xml; charset=utf-8");
  res.setHeader("Cache-Control", "public, s-maxage=3600, stale-while-revalidate=86400");
  res.write(buildSitemapXml(siteUrl));
  res.end();

  return {
    props: {},
  };
};

export default function SitemapXmlPage() {
  return null;
}
