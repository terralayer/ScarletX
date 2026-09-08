from pathlib import Path

path = Path("scarletx/usenet/worker.py")
text = path.read_text()
old = '''            else:
                bucket = self._age_bucket(segment)
                def score(provider: UsenetProviderConfig) -> float:
                    perf = self.perf[provider.name]
                    aged = self.age_perf[provider.name][bucket]
                    use_aged = aged["samples"] >= 2
                    throughput = max(1.0, float((aged if use_aged else perf)["ewma_bps"] or 0.0))
                    failures = aged["failures"] if use_aged else perf["failures"]
                    missing = aged["missing"] if use_aged else perf["missing"]
                    reliability = 1.0 / (1.0 + failures * 0.35 + missing * 0.22)
                    availability = max(0.10, 1.0 - self.pools[provider.name].utilization() * 0.90)
                    priority_bias = 1.0 / (1.0 + max(0, provider.priority - 1) * 0.01)
                    return throughput * reliability * availability * priority_bias
                primary = max(self.providers, key=score)
            rest = sorted(
                (p for p in self.providers if p.name != primary.name),
                key=lambda p: (-(self.perf[p.name]["ewma_bps"] or 0.0), p.priority),
            )
            return [primary, *rest]
'''
new = '''            else:
                bucket = self._age_bucket(segment)

                def score(provider: UsenetProviderConfig) -> float:
                    perf = self.perf[provider.name]
                    aged = self.age_perf[provider.name][bucket]
                    use_aged = aged["samples"] >= 2
                    throughput = max(1.0, float((aged if use_aged else perf)["ewma_bps"] or 0.0))
                    failures = aged["failures"] if use_aged else perf["failures"]
                    missing = aged["missing"] if use_aged else perf["missing"]
                    reliability = 1.0 / (1.0 + failures * 0.35 + missing * 0.22)
                    priority_bias = 1.0 / (1.0 + max(0, provider.priority - 1) * 0.01)
                    return throughput * reliability * priority_bias

                def rank(provider: UsenetProviderConfig) -> tuple[bool, float, float]:
                    utilization = self.pools[provider.name].utilization()
                    return utilization >= 1.0, utilization, -score(provider)

                ordered = sorted(self.providers, key=rank)
                primary, rest = ordered[0], ordered[1:]
                return [primary, *rest]
            rest = sorted(
                (p for p in self.providers if p.name != primary.name),
                key=lambda p: (-(self.perf[p.name]["ewma_bps"] or 0.0), p.priority),
            )
            return [primary, *rest]
'''
if text.count(old) != 1:
    raise SystemExit(f"expected exactly one provider-order block, found {text.count(old)}")
path.write_text(text.replace(old, new))
