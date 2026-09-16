import { ChevronDown, CircleAlert, Lightbulb, ShieldCheck } from 'lucide-react';
import { useState } from 'react';

import { Button } from '../components/ui/button';
import EvidencePanel from './EvidencePanel';
import type { Claim, ClaimKind, Confidence, Evidence } from './types';

const CLAIM_KIND_LABELS: Record<ClaimKind, string> = {
  fact: '事实',
  statistic: '统计',
  inference: 'AI 推断',
};

const CONFIDENCE_LABELS: Record<Confidence, string> = {
  low: '低可信度',
  medium: '中可信度',
  high: '高可信度',
};

const CLAIM_KIND_STYLES: Record<ClaimKind, string> = {
  fact: 'bg-sky-600/10 text-sky-800 dark:text-sky-200',
  statistic: 'bg-amber-600/10 text-amber-800 dark:text-amber-200',
  inference: 'bg-violet-600/10 text-violet-800 dark:text-violet-200',
};

const CONFIDENCE_STYLES: Record<Confidence, string> = {
  low: 'border-amber-300/70 text-amber-800 dark:border-amber-700/60 dark:text-amber-200',
  medium:
    'border-sky-300/70 text-sky-800 dark:border-sky-700/60 dark:text-sky-200',
  high: 'border-emerald-300/70 text-emerald-800 dark:border-emerald-700/60 dark:text-emerald-200',
};

export interface ClaimCardProps {
  claim: Claim;
  evidence: Evidence[];
}

export default function ClaimCard({ claim, evidence }: ClaimCardProps) {
  const [isEvidenceOpen, setIsEvidenceOpen] = useState(false);
  const evidenceById = new Map(evidence.map((source) => [source.id, source]));
  const claimEvidence = claim.evidence_ids
    .map((evidenceId) => evidenceById.get(evidenceId))
    .filter((source): source is Evidence => Boolean(source));
  const evidenceCount = claim.evidence_ids.length;
  const evidencePanelId = `${claim.id}-evidence`;
  const kindLabel = CLAIM_KIND_LABELS[claim.kind];
  const confidenceLabel = CONFIDENCE_LABELS[claim.confidence];

  return (
    <article className="rounded-2xl border border-black/10 bg-white/75 p-5 shadow-[0_16px_30px_-28px_rgba(30,40,30,0.85)] dark:border-white/10 dark:bg-white/[0.035]">
      <div className="flex flex-wrap items-center gap-2">
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-mono text-[10px] ${CLAIM_KIND_STYLES[claim.kind]}`}
        >
          {claim.kind === 'inference' ? (
            <Lightbulb className="size-3" />
          ) : (
            <ShieldCheck className="size-3" />
          )}
          {kindLabel}
        </span>
        <span
          className={`rounded-full border px-2.5 py-1 font-mono text-[10px] ${CONFIDENCE_STYLES[claim.confidence]}`}
        >
          {confidenceLabel}
        </span>
        {!evidenceCount && (
          <span className="inline-flex items-center gap-1 rounded-full bg-amber-600/10 px-2.5 py-1 font-mono text-[10px] text-amber-800 dark:text-amber-200">
            <CircleAlert className="size-3" />
            待补证据
          </span>
        )}
      </div>

      <p className="mt-4 text-[15px] leading-7 text-[#20241f] dark:text-[#f2f3e9]">
        {claim.text}
      </p>

      <div className="mt-4 flex items-center justify-between gap-3 border-t border-black/10 pt-3 dark:border-white/10">
        <span className="font-mono text-[10px] text-[#697267] dark:text-[#aeb8ac]">
          claim / {claim.id}
        </span>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={!evidenceCount}
          aria-controls={evidencePanelId}
          aria-expanded={isEvidenceOpen}
          onClick={() => setIsEvidenceOpen((open) => !open)}
          className="rounded-full px-3 text-[#1f6b4d] hover:bg-emerald-600/10 hover:text-[#18563e] dark:text-emerald-300 dark:hover:bg-emerald-400/10 dark:hover:text-emerald-200"
        >
          查看 {evidenceCount} 条证据
          <ChevronDown
            className={`size-3.5 transition-transform ${isEvidenceOpen ? 'rotate-180' : ''}`}
          />
        </Button>
      </div>

      {isEvidenceOpen && (
        <EvidencePanel
          id={evidencePanelId}
          evidence={claimEvidence}
          evidenceIds={claim.evidence_ids}
          heading="支持该结论的来源"
        />
      )}
    </article>
  );
}
