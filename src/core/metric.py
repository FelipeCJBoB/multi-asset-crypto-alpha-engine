"""`Metric`/`Unit`/`safe_ratio` — valor numérico reportável com unidade,
tamanho de amostra e proveniência anexados no próprio tipo.

**Por que isto existe.** Uma auditoria encontrou 3 achados na mesma
família, todos com a mesma causa raiz: o número certo era calculável a
partir do código, mas não vinha com metadado suficiente para interpretar
sem reler o código-fonte de novo.

1. `src.models.decomposition.carry_share = pnl_carry / pnl_total` sem
   checar o sinal de `pnl_total` — quando `pnl_total` é negativo (é, nos
   dados reais), a razão "passa" o gate (`abs(carry_share) < 0.30`) de um
   jeito que não testa o que o gate pretende. `safe_ratio` abaixo torna
   essa checagem estrutural (parâmetro `require_den_positive`), não uma
   convenção que cada chamador pode esquecer.
2. Um custo de execução circulou numa conversa sem unidade declarada — só
   ficou claro depois de reler o código que era soma de retorno fracionário
   por trade, não Sharpe, não bps, não % de equity. `Unit` torna a unidade
   parte do valor, não algo inferido do nome da variável.
3. Trades de 5 caminhos de CPCV somados foram lidos como uma série
   contínua. `n` + `n_semantics` tornam explícito o que está sendo contado
   — "trades" e "cpcv_paths" não são intercambiáveis mesmo quando ambos são
   só um `int`.

**Escopo deliberadamente pequeno.** Isto não é uma biblioteca de unidades
genérica (não há conversão automática entre `Unit`s, não há álgebra
dimensional tipo `pint`) — é um envelope fino o bastante para caber no
retorno de uma função existente sem reescrever o resto do repo. Aritmética
entre `Metric`s de unidades diferentes é um erro de programação, não um
caso a suportar — por isso `__add__`/`__sub__` levantam `ValueError` em vez
de tentar adivinhar uma conversão."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

# Fator de conversão fração -> pontos-base — definição matemática, não
# constante de domínio (mesma categoria de `_BPS_PER_UNIT` em
# `src.labels.triple_barrier`/`src.data.resample._TIMEFRAME_MINUTES`).
_BPS_PER_UNIT = 10_000


class Unit(StrEnum):
    """Unidades usadas pelos campos REPORTÁVEIS convertidos para `Metric`
    nesta rodada (`src.models.decomposition`, `src.backtest.fill_reconciliation`,
    `src.models.hhi`). Não é uma enumeração fechada para o repo inteiro —
    novo campo reportável com unidade que não se encaixa aqui adiciona um
    membro novo, não reaproveita um existente por conveniência (isso é
    exatamente o tipo de erro que este módulo existe para prevenir)."""

    BPS_PER_TRADE = "bps_per_trade"
    FRACTION_OF_NOTIONAL = "fraction_of_notional"
    RATIO = "ratio"
    COUNT = "count"
    SHARPE_ANNUALIZED = "sharpe_annualized"
    PROBABILITY = "probability"
    PERCENTAGE_POINTS = "percentage_points"


@dataclass(frozen=True, slots=True)
class Metric:
    """Valor numérico reportável + metadado suficiente para interpretar sem
    reler o código-fonte que o produziu.

    `n`/`n_semantics`: `n` é uma contagem (trades, caminhos de CPCV, barras,
    folds, ...) — `n_semantics` diz QUAL, como string livre (não é um enum
    fechado nesta v1 porque os chamadores atuais já cobrem `"trades"`,
    `"cpcv_paths"`, `"bars"`, `"folds"`, `"orders"`, `"signals"` sem um
    padrão comum óbvio o bastante para fechar a lista agora — fechar cedo
    demais reproduziria o mesmo erro nº3 da auditoria, só que ao contrário
    ("n_semantics" errado por engessamento em vez de por omissão).

    `valid`/`invalid_reason`: um `Metric` inválido (tipicamente produzido
    por `safe_ratio` quando o denominador falha o guard) carrega
    `value=nan` e `n`/`n_semantics` herdados normalmente — `n=0` NÃO é
    exigido para `valid=False` (o denominador pode ter falhado por sinal,
    não por amostra vazia); é só que, ao contrário de um `Metric` válido,
    `n` não precisa ser `> 0` (ver teste de propriedade em
    `tests/unit/test_core_metric.py`).

    `source`: dataset + versão/hash de origem do valor, ex. `"labels/v1"`
    ou `"experiments/alpha_layer1_report.json"` — o mesmo tipo de
    referência que faltava no achado nº2 da auditoria (custo de execução
    circulando sem se saber de onde vinha)."""

    value: float
    unit: Unit
    n: int
    n_semantics: str  # "trades" | "cpcv_paths" | "bars" | "folds" | ... — string livre, ver acima
    source: str  # dataset + versão/hash de origem, ex. "labels/v1" — ver docstring da classe
    valid: bool = True
    invalid_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        """Único caminho aprovado para um `Metric` entrar em relatório
        JSON — nunca `dataclasses.asdict()` implícito quando o chamador
        precisa do dict explicitamente (`Unit` vira `.value` string, não o
        objeto enum)."""
        return {
            "value": self.value,
            "unit": self.unit.value,
            "n": self.n,
            "n_semantics": self.n_semantics,
            "source": self.source,
            "valid": self.valid,
            "invalid_reason": self.invalid_reason,
        }

    def per_unit(self) -> Metric:
        """`value/n` convertido para bps, como novo `Metric(unit=BPS_PER_TRADE)`.

        Só definido para `unit=FRACTION_OF_NOTIONAL` sobre uma população com
        `n_semantics="trades"` — é exatamente a conversão que motivou este
        método: um `Metric` somado ao longo de N trades (ex. `pnl_total` em
        `src.models.decomposition`) dividido manualmente por `n` em
        múltiplos consumidores, com risco real de usar um `n` de um momento
        diferente do `value` (achado desta investigação — três consumidores
        distintos já leram `experiments/alpha_layer1_report.json` com essa
        divergência). Levanta `ValueError` para `unit`/`n_semantics` que não
        descrevem essa conversão — erro de uso do chamador, não condição de
        dado, então não segue o idioma `valid=False` de `safe_ratio`/
        `not_computable` (mesmo raciocínio de `__add__`/`__mul__` acima,
        que já levantam em vez de devolver `Metric` inválido para unidade
        incompatível).

        `n <= 0`, ao contrário, É uma condição de dado legítima (ex. saída
        de `not_computable`, que sempre tem `n=0`) — não levanta; devolve um
        `Metric(valid=False, value=nan)` propagando `n`/`source`, mesmo
        idioma de `safe_ratio` para denominador degenerado."""
        if self.unit != Unit.FRACTION_OF_NOTIONAL:
            raise ValueError(
                "per_unit() só converte Unit.FRACTION_OF_NOTIONAL para bps_per_trade; "
                f"unidade recebida: {self.unit.value}"
            )
        if self.n_semantics != "trades":
            raise ValueError(
                "per_unit() exige n_semantics='trades' (é a divisão que produz "
                f"'por trade'); recebido n_semantics={self.n_semantics!r}"
            )
        if self.n <= 0:
            return Metric(
                value=float("nan"),
                unit=Unit.BPS_PER_TRADE,
                n=self.n,
                n_semantics=self.n_semantics,
                source=self.source,
                valid=False,
                invalid_reason=self.invalid_reason or f"n={self.n} <= 0 — divisão indefinida",
            )
        return Metric(
            value=(self.value / self.n) * _BPS_PER_UNIT,
            unit=Unit.BPS_PER_TRADE,
            n=self.n,
            n_semantics=self.n_semantics,
            source=self.source,
            valid=self.valid,
            invalid_reason=self.invalid_reason,
        )

    def __add__(self, other: object) -> Metric:
        if not isinstance(other, Metric):
            return NotImplemented
        return self._combine(other, op=lambda a, b: a + b, op_name="somar")

    def __sub__(self, other: object) -> Metric:
        if not isinstance(other, Metric):
            return NotImplemented
        return self._combine(other, op=lambda a, b: a - b, op_name="subtrair")

    def _combine(
        self, other: Metric, *, op: Callable[[float, float], float], op_name: str
    ) -> Metric:
        """Núcleo comum de `__add__`/`__sub__` — `other` já confirmado
        `Metric` pelo chamador (o `isinstance` que decide `NotImplemented`
        precisa ficar no dunder em si para o protocolo de operador
        funcionar; ver `__radd__`/reflexão do Python). `n`/`n_semantics` do
        resultado são herdados de `self`, não somados — `Metric.__add__` é
        para combinar COMPONENTES da mesma população medida (ex.:
        `pnl_direcional + pnl_carry + pnl_execucao`, os três sobre os
        mesmos `n_trades`), não para agregar amostras independentes de
        tamanhos diferentes (isso é responsabilidade explícita de quem
        chama, fora da álgebra de `Metric`). Se `n`/`n_semantics` divergem
        entre os dois operandos, o resultado ainda usa os de `self`, mas
        fica com `valid=False` — divergência aqui é sinal de que os dois
        `Metric`s não descrevem a mesma população, o que é uma condição de
        erro silenciosa demais para deixar passar sem marca."""
        if self.unit != other.unit:
            raise ValueError(
                f"não é possível {op_name} Metric de unidades diferentes: "
                f"{self.unit.value} e {other.unit.value}"
            )
        n_mismatch = self.n != other.n or self.n_semantics != other.n_semantics
        valid = self.valid and other.valid and not n_mismatch
        invalid_reason = self.invalid_reason or other.invalid_reason
        if n_mismatch and invalid_reason is None:
            invalid_reason = (
                f"operandos de {op_name} descrevem populações diferentes: "
                f"n={self.n}/{self.n_semantics} vs n={other.n}/{other.n_semantics}"
            )
        return Metric(
            value=op(self.value, other.value),
            unit=self.unit,
            n=self.n,
            n_semantics=self.n_semantics,
            source=f"{self.source}+{other.source}",
            valid=valid,
            invalid_reason=invalid_reason,
        )

    def __mul__(self, scalar: object) -> Metric:
        """Multiplicação por escalar adimensional — permitida sem checagem
        de unidade (um fator linear sobre uma unidade aditiva continua na
        mesma unidade; é a operação que valida uma "cota superior
        especulativa", ex. `metric_por_trade * n_trades_projetado`).
        `Metric * Metric` NÃO é suportado — multiplicar duas quantidades
        com unidade normalmente muda a unidade do resultado (ex.
        fração x fração != fração), o que esta v1 deliberadamente não
        tenta resolver (ver docstring do módulo — não é uma lib de álgebra
        dimensional)."""
        if isinstance(scalar, Metric):
            raise TypeError(
                "Metric * Metric não é suportado (mudaria a unidade do resultado) — "
                "só Metric * escalar adimensional (int/float)"
            )
        if not isinstance(scalar, (int, float)):
            return NotImplemented
        return Metric(
            value=self.value * float(scalar),
            unit=self.unit,
            n=self.n,
            n_semantics=self.n_semantics,
            source=self.source,
            valid=self.valid,
            invalid_reason=self.invalid_reason,
        )

    def __rmul__(self, scalar: object) -> Metric:
        return self.__mul__(scalar)


def safe_ratio(
    num: Metric,
    den: Metric,
    *,
    require_den_positive: bool,
    unit: Unit,
    n_semantics: str,
    source: str,
) -> Metric:
    """`num.value / den.value` como `Metric` — com guard estrutural no
    denominador em vez de deixar cada chamador lembrar de checar.

    Se `require_den_positive` e `den.value` não for finito e positivo
    (`<= 0`, `nan`, `inf`), devolve um `Metric` `valid=False` com
    `value=nan` em vez de calcular a razão — é exatamente o achado nº1 da
    auditoria (`carry_share` "passando" um gate por acidente quando
    `pnl_total < 0`): o guard precisa impedir o CÁLCULO, não só documentar
    que o resultado seria suspeito.

    `n`/`n_semantics` do resultado são herdados de `num`, não de `den` —
    uma razão continua descrevendo a população do numerador (ex.
    `carry_share` sobre os mesmos `n_trades` de `pnl_carry`); `den` entra
    só como divisor, não como amostra do resultado. Se o chamador quer
    `n`/`n_semantics` diferentes (caso legítimo, ex. uma taxa por uma
    unidade de tempo), passe explicitamente via `n_semantics` e construa o
    `Metric` final fora desta função — `safe_ratio` não adivinha."""
    den_invalid = require_den_positive and not (math.isfinite(den.value) and den.value > 0.0)
    if den_invalid:
        return Metric(
            value=float("nan"),
            unit=unit,
            n=num.n,
            n_semantics=n_semantics,
            source=source,
            valid=False,
            invalid_reason=f"denominador {den.value} <= 0 (ou não-finito)",
        )
    try:
        # `require_den_positive=False` opta por não exigir sinal, mas
        # divisão por zero literal ainda levanta ZeroDivisionError em
        # Python (ao contrário de numpy, que devolveria inf/nan
        # silenciosamente) — capturado aqui para que "safe" em safe_ratio
        # valha para os dois modos, não só o guardado por sinal.
        value = num.value / den.value
    except ZeroDivisionError:
        return Metric(
            value=float("nan"),
            unit=unit,
            n=num.n,
            n_semantics=n_semantics,
            source=source,
            valid=False,
            invalid_reason=f"denominador {den.value} == 0 (divisão por zero)",
        )
    return Metric(
        value=value,
        unit=unit,
        n=num.n,
        n_semantics=n_semantics,
        source=source,
        valid=num.valid and den.valid,
        invalid_reason=num.invalid_reason or den.invalid_reason,
    )


def not_computable(unit: Unit, n_semantics: str, source: str, reason: str) -> Metric:
    """`Metric` para a categoria "nunca foi medido" — mesmo formato que
    `safe_ratio` já produz para "denominador inválido" (`value=nan`,
    `valid=False`, `invalid_reason=reason`), mas com nome próprio para o
    caso em que a POPULAÇÃO em si nunca existiu para medir: feature
    indisponível, sensor sem fonte de dado ao vivo, ou uma fatia do dado
    que nunca teve amostra válida (ex.: regime `R0` em
    `tests/unit/test_models_dataset.py` — 100% warmup, nenhuma barra chega
    a ter as 10 features T1 não-nulas, então "contagem de trades em R0" é
    NOT_COMPUTABLE, não `0` medido). Mesmo princípio do sentinela tri-
    valorado já usado em `TriggerState.NOT_COMPUTABLE`
    (`src.regime.stress`, `src.risk.kill_switch`) e
    `ControlOutcome.NOT_COMPUTABLE` (`src.risk.limits`): "não sei" precisa
    ser um estado explícito no tipo, nunca um `False`/`0.0` silencioso
    quando o dado não existe.

    `n=0` aqui é consequência de "população nunca existiu", não um
    parâmetro livre — este factory não aceita `n` porque não há amostra
    nenhuma para contar. **A distinção que separa este caso de "zero
    medido de fato" NÃO é `n` (um `Metric(value=0.0, n=0, valid=True,
    ...)` também é uma construção permitida pelo dataclass, embora
    incomum) — é `valid`.** `not_computable(...)` sempre devolve
    `valid=False`; um caller que quer registrar "medi e deu exatamente
    zero" continua construindo `Metric(...)` diretamente com `valid=True`,
    nunca por este factory.

    `__add__`/`__sub__` (`Metric._combine`) já propagam `valid=False` de
    qualquer operando inválido para o resultado — um agregador que soma
    `Metric`s não trata `not_computable` como `0.0` silencioso: o `value`
    do resultado também vira `nan` (`nan + x == nan`), e `valid=False`
    fica visível em qualquer checagem posterior. Ver
    `test_not_computable_dominante_em_soma_nao_vira_zero_silencioso` em
    `tests/unit/test_core_metric.py`."""
    return Metric(
        value=float("nan"),
        unit=unit,
        n=0,
        n_semantics=n_semantics,
        source=source,
        valid=False,
        invalid_reason=reason,
    )
