"use client";

import { useLang } from "@/lib/i18n";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{title}</h2>
      <div className="space-y-3 text-zinc-600 dark:text-zinc-400">{children}</div>
    </section>
  );
}

export default function AboutContent() {
  const { t } = useLang();
  return (
    <div className="mx-auto max-w-2xl space-y-8">
      <div>
        <h1 className="text-2xl font-bold">{t.about.title}</h1>
        <p className="mt-2 text-zinc-600 dark:text-zinc-400">{t.about.intro}</p>
      </div>

      <Section title={t.about.whatTitle}>
        <p>{t.about.whatBody}</p>
      </Section>

      <Section title={t.about.dataTitle}>
        <p>{t.about.dataBody}</p>
      </Section>

      <Section title={t.about.modelsTitle}>
        <p>{t.about.modelsBody1}</p>
        <p>{t.about.modelsBody2}</p>
      </Section>

      <Section title={t.about.cycleTitle}>
        <p>{t.about.cycleBody}</p>
      </Section>

      <Section title={t.about.honestTitle}>
        <p>{t.about.honestBody}</p>
      </Section>

      <Section title={t.about.notTitle}>
        <p>{t.about.notBody}</p>
      </Section>

      <Section title={t.about.hoodTitle}>
        <p>
          {t.about.hoodBody}
          <a href="https://hoopmodel.com" className="underline">
            {t.about.hoodLink}
          </a>
          {t.about.hoodBodyEnd}
        </p>
      </Section>
    </div>
  );
}
