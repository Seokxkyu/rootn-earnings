# Archived: Initial Capital IQ Browser Test

This document records the original PDF and Trip.com proof of concept. It is
historical evidence, not the current collection specification.

Last updated: 2026-07-09 (Asia/Seoul)

## Summary

- Test target URL: `https://www.capitaliq.spglobal.com/web/client?auth=inherit#news/transcriptsSummary`
- Result: success
- Verified flow: login -> email MFA -> transcripts page -> top-row PDF download
- Sensitive credentials: intentionally not stored in this file

## What was verified

1. The site redirected from the transcript summary URL to the S&P Global sign-in flow.
2. Email address entry succeeded.
3. Password entry succeeded.
4. An email-based 4-digit MFA token was required before access was granted.
5. After MFA, the app opened `Transcripts & Investor Presentations`.
6. The top row transcript PDF button triggered a real file download.

## Successful download check

- Downloaded item tested: `Trip.com Group Limited, Q3 2025 Earnings Call, Nov 17, 2025`
- Local file observed: `C:\Users\rootn\Downloads\Trip.com Group Limited_Earnings Call_2025-11-18_English (2).pdf`
- File size observed during test: `406,689 bytes`
- Download confirmation signals:
  - On-page toast: `Download started`
  - Local file creation confirmed in `Downloads`

## Automation notes

- MFA is the main interactive checkpoint.
- The transcript list is rendered as a grid with repeated PDF/WORD/MP3 controls per row.
- Bulk collection should use:
  - row-level scoping
  - per-download completion checks
  - duplicate filename handling
  - pagination support when needed

## Suggested next step

Convert this verified manual browser flow into a repeatable collector that:

- logs in
- pauses for MFA input
- filters target rows
- downloads multiple PDFs
- confirms each file was actually created
