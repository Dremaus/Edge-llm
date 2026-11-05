# Decyzje architektoniczne

Krótki rejestr decyzji. Szczegóły i uzasadnienia: dokument projektowy
https://claude.ai/artifact/WgErVzXtiF86DtRptPqoMX

| Data | Decyzja | Uzasadnienie |
| --- | --- | --- |
| 2026-10-31 | Modele z Hugging Face (GGUF), bez trenowania własnych | Szybki start, licencje Apache 2.0 |
| 2026-10-31 | Jeden model dwujęzyczny: Qwen3.5-4B | Prostsze utrzymanie; Bielik jako alternatywa w ustawieniach |
| 2026-10-31 | Wybór języka PL/EN przy pierwszym uruchomieniu | Ustawia język aplikacji i odpowiedzi modelu |
| 2026-10-31 | LangGraph jako rdzeń orkiestracji | Graf stanów, checkpointy w SQLite, MCP, Python |
| 2026-10-31 | Router w MVP: reguły + Qwen3.5-0.8B | Prosty i przewidywalny; NeMo Switchyard do testów w fazie 5 |
| 2026-10-31 | Bez bramy LLM (LiteLLM, Portkey) | Jeden backend na urządzeniu — Ollama |
| 2026-10-31 | Narzędzia przez MCP | Niezależność od frameworka agentowego |
| 2026-10-31 | Tailscale na start | Najszybsze wdrożenie; potem własny relay z E2E |
| 2026-10-31 | Licencja Apache 2.0 | Zgodna z licencjami modeli i bibliotek |
| 2026-10-31 | Bezpieczeństwo: domyślna odmowa i obrona warstwowa | Tylko localhost + Tailscale, tokeny per telefon, piaskownica systemd; szczegóły w docs/security.md |
| 2026-10-31 | ~~Do zbadania: mini PC x86 (Ryzen 7, 32 GB) zamiast Jetsona~~ | Rozstrzygnięte niżej |
| 2026-10-31 | **Platforma: mini PC z AMD Ryzen AI** zamiast Jetsona | Taniej przy 16–32 GB pamięci; x86 + Ubuntu 24.04; TPM i Secure Boot do szyfrowania dysku; NPU na później. Szczegóły: docs/hardware.md |
| 2026-10-31 | Ollama na Radeonie przez Vulkan, nie ROCm | ~2× szybsze generowanie w pomiarach; działa na wszystkich Ryzen AI |
| 2026-11-05 | Skład modeli według RAM (kandydaci) | 32 GB: Gemma 4 26B-A4B (HauhauCS) + Ornith-1.5-35B-A3B (kod, na żądanie); 16 GB: Gemma-4-E4B + Ornith-1.5-9B; router Qwen3.5-0.8B; Bielik zawsze. Wszystko ze statusem `candidate` do tygodnia testów (licencja Gemma, polski, narzędzia, odporność na złośliwy dokument). Odrzucone: modele „Claude/Fable distill" (warunki Anthropic), gęste 27–33B (ok. 5 tok/s), 100B+. |
