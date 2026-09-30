"""
Synthetic Bitcoin traffic generator.

Real labelled captures that join P2P announcements to transactions are not publicly
available, so models are trained and evaluated on simulated traffic: ordinary wallet
activity, exchange batching and sweeps, and look-alike payout services, mixed with
laundering typologies (peeling chains, CoinJoin rounds, structuring, cash-out sweeps).
Every value is generated from a seed; nothing here is real transaction data.

Usage:
    python -m src.simulation.generator --seed 7
"""
import argparse
import csv
import hashlib
import ipaddress
import json
import random
from pathlib import Path
from typing import Dict, List, Tuple

from config.settings import DEMO_DATA_DIR, DEMO_GROUND_TRUTH
from src.ingestion.parser import Dataset

SENSORS = ["198.51.100.11", "198.51.100.12", "198.51.100.13", "198.51.100.14"]

NETWORKS = {
    "jio": "49.36.0.0/14", "airtel": "106.192.0.0/11", "bsnl": "117.192.0.0/10",
    "comcast": "73.0.0.0/8", "dtag": "91.0.0.0/10",
    "vpn_m247": "146.70.0.0/16", "vpn_31173": "193.32.126.0/24",
    "hosting_do": "159.65.0.0/16", "hosting_hetzner": "95.216.0.0/16",
    "tor_a": "185.220.100.0/24", "tor_b": "185.220.101.0/24", "tor_c": "104.244.72.0/21",
    "exchange": "203.0.113.0/24",
}
USER_NETWORKS = ["jio", "airtel", "bsnl", "comcast", "dtag", "vpn_m247", "hosting_do", "tor_b"]
USER_NETWORK_WEIGHTS = [30, 25, 10, 12, 8, 8, 5, 2]

_BECH32 = "qpzry9x8gf2tvdw0s3jn54khce6mua7l"
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
DUST = 546e-8

Coin = Tuple[str, float]  # (address, amount in BTC)


class TrafficSimulator:
    def __init__(self, seed: int = 7, start_ts: float = 1790000000.0,
                 duration_s: float = 6 * 3600.0, n_users: int = 90):
        self.seed = seed
        self.rng = random.Random(seed)
        self.start_ts = start_ts
        self.duration_s = duration_s
        self.n_users = n_users
        self._addr_n = 0
        self._tx_n = 0
        self.transactions: List[Dict] = []
        self.observations: List[Dict] = []
        self.truth: Dict[str, Dict] = {}

        self.relays = ([self._ip("hosting_do") for _ in range(10)]
                       + [self._ip("hosting_hetzner") for _ in range(8)]
                       + [self._ip("comcast") for _ in range(4)]
                       + [self._ip("dtag") for _ in range(4)])
        self.tor_exits = [self._ip(name) for name in ("tor_a", "tor_a", "tor_b", "tor_b", "tor_b", "tor_c", "tor_c")]

    # ------------------------------------------------------------------ primitives

    def _ip(self, network: str) -> str:
        net = ipaddress.ip_network(NETWORKS[network])
        return str(net[self.rng.randrange(1, net.num_addresses - 1)])

    def _address(self) -> str:
        self._addr_n += 1
        seed = f"{self.seed}:addr:{self._addr_n}".encode()
        digest = hashlib.sha256(seed).digest() + hashlib.sha256(seed + b"+").digest()
        kind = self.rng.choices(["bc1q", "1", "3"], weights=[70, 20, 10])[0]
        if kind == "bc1q":
            return kind + "".join(_BECH32[b % 32] for b in digest[:38])
        return kind + "".join(_BASE58[b % 58] for b in digest[:33])

    def _rate(self, scripted: bool = False) -> float:
        """Fee rate in sat/vB. Scripted laundering often, not always, overpays for fast confirmation."""
        mu, sigma = (3.3, 0.5) if scripted else (2.7, 0.5)
        return min(max(self.rng.lognormvariate(mu, sigma), 2.0), 150.0)

    @staticmethod
    def _fee(n_in: int, n_out: int, rate: float) -> float:
        return (10.5 + 68.0 * n_in + 31.0 * n_out) * rate * 1e-8

    def _observe(self, txid: str, ts: float, origin_ip: str) -> None:
        """
        Each sensor hears the transaction from one or two relay peers, and with 50%
        probability directly from the origin. So the origin is sometimes invisible, and
        a relay can occasionally win the race: attribution is genuinely uncertain.
        """
        origin_port = self.rng.randrange(49152, 65535)
        for sensor in SENSORS:
            if self.rng.random() < 0.5:
                self._record(ts + 0.01 + self.rng.expovariate(1 / 0.04), origin_ip, origin_port, sensor, txid)
            for _ in range(1 if self.rng.random() < 0.7 else 2):
                self._record(ts + 0.07 + self.rng.expovariate(1 / 0.25), self.rng.choice(self.relays), 8333, sensor, txid)

    def _record(self, ts: float, src_ip: str, src_port: int, dst_ip: str, txid: str) -> None:
        self.observations.append({
            "timestamp": round(ts, 4), "src_ip": src_ip, "src_port": src_port,
            "dst_ip": dst_ip, "dst_port": 8333, "txid": txid,
        })

    def _emit(self, ts: float, origin_ip: str, inputs: List[Coin], outputs: List[Coin],
              typology: str = "normal", scenario: str = None) -> str:
        self._tx_n += 1
        txid = hashlib.sha256(f"{self.seed}:tx:{self._tx_n}".encode()).hexdigest()
        outputs = [(a, round(v, 8)) for a, v in outputs]
        inputs = [(a, round(v, 8)) for a, v in inputs]
        first = inputs[0][0]
        self.transactions.append({
            "txid": txid,
            "input_addresses": [a for a, _ in inputs],
            "output_addresses": [a for a, _ in outputs],
            "input_amounts": [v for _, v in inputs],
            "output_amounts": [v for _, v in outputs],
            "fee": round(sum(v for _, v in inputs) - sum(v for _, v in outputs), 8),
            "script_type": "P2WPKH" if first.startswith("bc1q") else ("P2SH" if first.startswith("3") else "P2PKH"),
        })
        self._observe(txid, ts, origin_ip)
        self.truth[txid] = {
            "label": int(typology != "normal"), "typology": typology, "scenario": scenario,
            "origin_ip": origin_ip, "timestamp": round(ts, 4),
        }
        return txid

    def _pay(self, ts: float, origin_ip: str, inputs: List[Coin], pays: List[Coin], change_addr: str,
             rate: float, typology: str = "normal", scenario: str = None) -> float:
        """Pays `pays`, returns the change amount sent to `change_addr` (0 if below dust)."""
        fee = self._fee(len(inputs), len(pays) + 1, rate)
        change = sum(v for _, v in inputs) - sum(v for _, v in pays) - fee
        outputs = list(pays)
        if change > DUST:
            outputs.append((change_addr, change))
            self.rng.shuffle(outputs)
        self._emit(ts, origin_ip, inputs, outputs, typology, scenario)
        return round(change, 8) if change > DUST else 0.0

    def _sweep(self, ts: float, origin_ip: str, inputs: List[Coin], dest_addr: str, rate: float,
               typology: str = "normal", scenario: str = None) -> float:
        """Merges every input into one output; returns the amount received."""
        amount = sum(v for _, v in inputs) - self._fee(len(inputs), 1, rate)
        self._emit(ts, origin_ip, inputs, [(dest_addr, amount)], typology, scenario)
        return round(amount, 8)

    # ------------------------------------------------------------------ benign traffic

    def _benign(self) -> None:
        rng = self.rng
        users = []
        for _ in range(self.n_users):
            network = rng.choices(USER_NETWORKS, weights=USER_NETWORK_WEIGHTS)[0]
            coins = [(self._address(), min(max(rng.lognormvariate(-1.0, 1.2), 0.005), 8.0))
                     for _ in range(rng.randint(1, 4))]
            users.append({"ip": self._ip(network), "coins": coins})
        # Some real origins also relay other people's transactions, so "this IP relays a
        # lot" lowers confidence in an attribution without ruling it out.
        self.relays += [user["ip"] for user in rng.sample(users, k=max(1, self.n_users // 12))]

        exchanges = [{"ip": self._ip("exchange"),
                      "coins": [(self._address(), rng.uniform(40, 150)) for _ in range(3)]} for _ in range(2)]
        self.exchange_ips = [exchange["ip"] for exchange in exchanges]
        self.relays += [exchange["ip"] for exchange in exchanges]
        services = [{"ip": self._ip(net), "coin": (self._address(), rng.uniform(5, 15))}
                    for net in ("hosting_do", "hosting_hetzner")]

        events = []  # (time, kind, actor index)
        for idx in range(len(users)):
            for _ in range(rng.randint(1, 7)):
                t = rng.uniform(0, self.duration_s)
                events.append((t, "user", idx))
                if rng.random() < 0.2:  # a second payment in the same sitting
                    events.append((t + rng.uniform(30, 300), "user", idx))
        for idx in range(len(exchanges)):
            t = rng.uniform(0, 1200)
            while t < self.duration_s:
                events.append((t, "withdrawal", idx))
                t += rng.expovariate(1 / 1800.0)
            t = rng.uniform(0, 3600)
            while t < self.duration_s:
                events.append((t, "deposit_sweep", idx))
                t += rng.expovariate(1 / 3600.0)
        for idx in range(len(services)):
            t = rng.uniform(0, 3600)
            while t < self.duration_s:
                events.append((t, "payout", idx))
                t += rng.uniform(8 * 60, 40 * 60)

        for offset, kind, idx in sorted(events):
            ts = self.start_ts + offset
            if kind == "user":
                self._user_tx(ts, users, idx)
            elif kind == "withdrawal":
                exchange = exchanges[idx]
                exchange["coins"].sort(key=lambda c: c[1])
                coin = exchange["coins"].pop()
                amounts = [min(max(rng.lognormvariate(-1.5, 1.0), 0.01), 3.0) for _ in range(rng.randint(6, 18))]
                scale = min(1.0, 0.6 * coin[1] / sum(amounts))
                pays = []
                for amount in amounts:
                    payee, addr = rng.choice(users), self._address()
                    pays.append((addr, amount * scale))
                    payee["coins"].append((addr, round(amount * scale, 8)))
                change_addr = self._address()
                change = self._pay(ts, exchange["ip"], [coin], pays, change_addr, self._rate())
                exchange["coins"].append((change_addr, change))
            elif kind == "deposit_sweep":
                exchange = exchanges[idx]
                deposits = [(self._address(), rng.uniform(0.05, 2.0)) for _ in range(rng.randint(8, 15))]
                hot = self._address()
                exchange["coins"].append((hot, self._sweep(ts, exchange["ip"], deposits, hot, self._rate())))
            else:  # payout service: a benign chain that looks like peeling, but slow and chunky
                service = services[idx]
                addr, balance = service["coin"]
                if balance < 0.05:
                    continue
                payee, pay_addr, change_addr = rng.choice(users), self._address(), self._address()
                amount = balance * rng.uniform(0.03, 0.2)
                payee["coins"].append((pay_addr, amount))
                change = self._pay(ts, service["ip"], [(addr, balance)], [(pay_addr, amount)], change_addr, self._rate())
                service["coin"] = (change_addr, change)

    def _user_tx(self, ts: float, users: List[Dict], idx: int) -> None:
        rng, user = self.rng, users[idx]
        coins = user["coins"]
        if not coins:
            return
        if len(coins) >= 3 and rng.random() < 0.2:
            addr = self._address()
            user["coins"] = [(addr, self._sweep(ts, user["ip"], coins, addr, self._rate()))]
            return
        coins.sort(key=lambda c: c[1])
        spend = [coins.pop() if rng.random() < 0.5 else coins.pop(rng.randrange(len(coins)))]
        if coins and rng.random() < 0.15:
            spend.append(coins.pop(rng.randrange(len(coins))))
        total = sum(v for _, v in spend)
        amount = total * rng.uniform(0.03, 0.9)
        if total - amount < 0.0005:
            user["coins"] += spend
            return
        pay_addr, change_addr = self._address(), self._address()
        if rng.random() < 0.6:
            rng.choice(users)["coins"].append((pay_addr, amount))
        change = self._pay(ts, user["ip"], spend, [(pay_addr, amount)], change_addr, self._rate())
        if change:
            user["coins"].append((change_addr, change))

    # ------------------------------------------------------------------ laundering typologies

    def _actor(self) -> Dict:
        """
        One laundering operation's habits. Most are scripted, fast and hidden behind Tor
        or a VPN, but not all: some are patient, pay ordinary fees, or run from a rented
        server or a compromised residential host. Those are the hard ones to catch.
        """
        rng = self.rng
        network = rng.choices(["tor", "vpn", "hosting", "residential"], weights=[50, 30, 10, 10])[0]
        fixed_ip = {
            "tor": None,
            "vpn": self._ip(rng.choice(["vpn_m247", "vpn_31173"])),
            "hosting": self._ip(rng.choice(["hosting_do", "hosting_hetzner"])),
            "residential": self._ip(rng.choice(["jio", "airtel", "comcast"])),
        }[network]
        return {"fixed_ip": fixed_ip, "patient": rng.random() < 0.3, "scripted_fees": rng.random() < 0.6}

    def _actor_ip(self, actor: Dict) -> str:
        return actor["fixed_ip"] or self.rng.choice(self.tor_exits)

    def _actor_gap(self, actor: Dict) -> float:
        return self.rng.uniform(300, 1500) if actor["patient"] else self.rng.uniform(8, 90)

    def _walk(self, ts: float, balance: float, hops: int, actor: Dict, typology: str, scenario: str):
        """
        A run of (1 input -> small payment + large remainder) hops. Used both for
        laundering peel chains and for their benign twin, so that the two are drawn from
        the same on-chain distribution and only context can tell them apart.
        """
        rng = self.rng
        low, high = (0.005, 0.04) if rng.random() < 0.7 else (0.04, 0.15)
        addr, peeled = self._address(), []
        for _ in range(hops):
            peel_addr, change_addr = self._address(), self._address()
            amount = balance * rng.uniform(low, high)
            balance = self._pay(ts, self._actor_ip(actor), [(addr, balance)], [(peel_addr, amount)], change_addr,
                                self._rate(actor["scripted_fees"]), typology, scenario)
            peeled.append((peel_addr, amount))
            addr = change_addr
            ts += self._actor_gap(actor)
        return peeled, ts

    def _peel_chain(self, scenario: str, ts: float, balance: float, hops: int) -> None:
        rng, actor = self.rng, self._actor()
        peeled, ts = self._walk(ts, balance, hops, actor, "peel_chain", scenario)
        if rng.random() < 0.4:
            return  # the proceeds are left to sit beyond the capture window
        # Cash-out: most peeled outputs are swept to one deposit address...
        batch = rng.sample(peeled, k=max(3, int(len(peeled) * rng.uniform(0.5, 0.7))))
        self._sweep(ts + rng.uniform(600, 1800), self._actor_ip(actor), batch, self._address(),
                    self._rate(actor["scripted_fees"]), "cashout", scenario)
        # ...and a few are forwarded one by one by money mules on ordinary residential
        # lines, paying ordinary fees. Individually these look like any other payment.
        rest = [coin for coin in peeled if coin not in batch]
        for coin in rest[:rng.randint(0, 3)]:
            self._sweep(ts + rng.uniform(900, 5400), self._ip(rng.choice(["jio", "airtel", "bsnl"])),
                        [coin], self._address(), self._rate(), "layering", scenario)

    def _hot_wallet_chain(self, ts: float) -> None:
        """
        Benign twin of a peel chain: an exchange or payment processor paying customers
        one withdrawal at a time from a hot wallet. On-chain it has the same shape,
        speed and fees as laundering; what differs is who announces it.
        """
        rng = self.rng
        ip = rng.choice(self.exchange_ips) if rng.random() < 0.7 else self._ip(
            rng.choice(["hosting_do", "hosting_hetzner"]))
        actor = {"fixed_ip": ip, "patient": rng.random() < 0.3, "scripted_fees": rng.random() < 0.6}
        self._walk(ts, rng.uniform(20, 60), rng.randint(9, 16), actor, "normal", None)

    def _coinjoin(self, scenario: str, ts: float) -> None:
        rng, actor = self.rng, self._actor()
        n = rng.randint(5, 9)
        denomination = rng.choice([0.1, 0.5, 1.0])
        fee_share = self._fee(n, 2 * n, self._rate(actor["scripted_fees"])) / n
        inputs = [(self._address(), denomination + rng.uniform(0.002, 0.4 * denomination)) for _ in range(n)]
        mixed = [(self._address(), denomination) for _ in range(n)]
        change = [(self._address(), value - denomination - fee_share) for _, value in inputs]
        outputs = mixed + change
        rng.shuffle(outputs)
        self._emit(ts, self._actor_ip(actor), inputs, outputs, "coinjoin", scenario)

        # Some mixed outputs are then walked off through short peel chains.
        for addr, value in rng.sample(mixed, k=rng.randint(1, 2)):
            t = ts + rng.uniform(60, 600)
            for _ in range(rng.randint(3, 5)):
                peel_addr, change_addr = self._address(), self._address()
                amount = value * rng.uniform(0.02, 0.1)
                value = self._pay(t, self._actor_ip(actor), [(addr, value)], [(peel_addr, amount)],
                                  change_addr, self._rate(actor["scripted_fees"]), "peel_chain", scenario)
                addr = change_addr
                t += self._actor_gap(actor)

    def _structuring(self, scenario: str, ts: float) -> None:
        """Fan-out into near-equal parts, one layering hop each, then fan-in."""
        rng, actor = self.rng, self._actor()
        rate = lambda: self._rate(actor["scripted_fees"])
        total = rng.uniform(8, 15)
        k = rng.randint(9, 14)
        weights = [rng.uniform(0.85, 1.15) for _ in range(k)]
        spendable = total - self._fee(1, k, rate())
        parts = [(self._address(), spendable * w / sum(weights)) for w in weights]
        self._emit(ts, self._actor_ip(actor), [(self._address(), total)], parts, "structuring", scenario)

        layered, latest = [], ts
        for coin in parts:
            t = ts + self._actor_gap(actor) * rng.uniform(1, 4)
            dest = self._address()
            layered.append((dest, self._sweep(t, self._actor_ip(actor), [coin], dest, rate(), "structuring", scenario)))
            latest = max(latest, t)
        split = rng.randint(1, 2)
        for group in (layered[i::split] for i in range(split)):
            latest += rng.uniform(60, 600)
            self._sweep(latest, self._actor_ip(actor), group, self._address(), rate(), "structuring", scenario)

    # ------------------------------------------------------------------ public API

    def generate(self, n_peel: int = None, n_coinjoin: int = None, n_structuring: int = None,
                 n_hot_wallet: int = None) -> "TrafficSimulator":
        rng = self.rng
        self._benign()
        window = lambda: self.start_ts + rng.uniform(0.05, 0.85) * self.duration_s
        for i in range(n_peel if n_peel is not None else rng.randint(2, 4)):
            self._peel_chain(f"PEEL-{i + 1}", window(), rng.uniform(20, 60), rng.randint(9, 16))
        for i in range(n_coinjoin if n_coinjoin is not None else rng.randint(2, 4)):
            self._coinjoin(f"MIX-{i + 1}", window())
        for i in range(n_structuring if n_structuring is not None else rng.randint(1, 3)):
            self._structuring(f"STRUCT-{i + 1}", window())
        for _ in range(n_hot_wallet if n_hot_wallet is not None else rng.randint(2, 4)):
            self._hot_wallet_chain(window())

        # Capture files are ordered by arrival; the ledger extract carries no time order.
        self.observations.sort(key=lambda o: o["timestamp"])
        self.transactions.sort(key=lambda tx: tx["txid"])
        return self

    def dataset(self) -> Dataset:
        return Dataset(
            observations=[dict(o) for o in self.observations],
            transactions={tx["txid"]: dict(tx) for tx in self.transactions},
            sources=[{"file": f"simulation(seed={self.seed})", "sha256": None, "records": len(self.observations)}],
        )

    def write(self, out_dir: Path, truth_path: Path) -> None:
        out_dir, truth_path = Path(out_dir), Path(truth_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        truth_path.parent.mkdir(parents=True, exist_ok=True)

        with open(out_dir / "network_observations.csv", "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp", "src_ip", "src_port", "dst_ip", "dst_port", "txid"])
            writer.writeheader()
            writer.writerows(self.observations)
        with open(out_dir / "blockchain_transactions.json", "w", encoding="utf-8", newline="\n") as f:
            f.write("[\n" + ",\n".join(json.dumps(tx) for tx in self.transactions) + "\n]\n")
        with open(truth_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump({"seed": self.seed, "transactions": self.truth}, f, indent=0, sort_keys=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a synthetic two-layer Bitcoin traffic capture.")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=DEMO_DATA_DIR)
    parser.add_argument("--truth", type=Path, default=DEMO_GROUND_TRUTH)
    args = parser.parse_args()

    sim = TrafficSimulator(seed=args.seed).generate(n_peel=4, n_coinjoin=3, n_structuring=2, n_hot_wallet=3)
    sim.write(args.out, args.truth)
    suspicious = sum(t["label"] for t in sim.truth.values())
    print(f"[+] {len(sim.transactions)} transactions ({suspicious} in laundering scenarios), "
          f"{len(sim.observations)} network observations -> {args.out}")


if __name__ == "__main__":
    main()
