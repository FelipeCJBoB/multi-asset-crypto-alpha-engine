"""Smoke test das 3 dependências novas de M4 (`PRD_V4_1.md` §3.2, plano
de execução, Fase 0) -- `dynamax`+`jax`/`jaxlib` (HMM gaussiano) e
`jumpmodels` (Jump Model contínuo). NÃO decide a API final de
`src/regime/hmm_gaussian.py`/`jump_model.py` -- só confirma que as libs
importam e rodam sobre dado sintético no Windows/CPU deste ambiente,
ANTES de escrever qualquer código real em cima delas (risco real
sinalizado no plano: JAX nunca foi usado neste repo).

Cada bloco é isolado (try/except próprio) -- uma falha não impede testar
os outros 2. Roda em segundos, sem tocar disco/dado real. B28 (proibido
`print()`) -- todo output via `structlog`, inclusive listagem exploratória
de API (`dir()`/atributos), mesmo padrão do resto de `tools/diagnostics/`."""

from __future__ import annotations

import sys
import traceback

import numpy as np
import structlog

logger = structlog.get_logger(__name__)


def _smoke_test_jax() -> bool:
    try:
        import jax
        import jax.numpy as jnp

        x = jnp.array([1.0, 2.0, 3.0])
        y = float(jnp.sum(x * 2.0))
        logger.info(
            "smoke_test_m4.jax",
            jax_version=jax.__version__,
            devices=str(jax.devices()),
            soma_1_2_3_vezes_2=y,
            esperado=12.0,
            ok=(y == 12.0),
        )
        return y == 12.0
    except Exception:
        logger.warning("smoke_test_m4.jax_falhou", traceback=traceback.format_exc())
        return False


def _smoke_test_dynamax() -> bool:
    try:
        import dynamax

        logger.info(
            "smoke_test_m4.dynamax_import",
            file=dynamax.__file__,
            version=getattr(dynamax, "__version__", "N/A"),
        )

        try:
            from dynamax.hidden_markov_model import GaussianHMM

            logger.info("smoke_test_m4.dynamax_gaussian_hmm_import_ok")
        except ImportError:
            import pkgutil

            submodules = [m.name for m in pkgutil.iter_modules(dynamax.__path__, prefix="dynamax.")]
            logger.warning(
                "smoke_test_m4.dynamax_gaussian_hmm_import_falhou_listando_pacote",
                submodules=submodules,
            )
            raise

        import jax.numpy as jnp
        from jax import random as jax_random

        rng_key = jax_random.PRNGKey(0)
        n_states = 2
        emission_dim = 1
        hmm = GaussianHMM(n_states, emission_dim)
        params, props = hmm.initialize(rng_key)
        logger.info("smoke_test_m4.dynamax_initialize_ok", params_type=str(type(params)))

        rng_data = np.random.default_rng(0)
        obs = rng_data.normal(0.0, 1.0, size=(200, 1)).astype(np.float32)
        obs_jax = jnp.asarray(obs)
        fitted_params, log_probs = hmm.fit_em(params, props, obs_jax, num_iters=5)
        logger.info(
            "smoke_test_m4.dynamax_fit_em_ok",
            log_probs_finais=[float(x) for x in log_probs[-3:]],
        )

        posterior = hmm.filter(fitted_params, obs_jax)
        attrs = [a for a in dir(posterior) if not a.startswith("_")]
        logger.info(
            "smoke_test_m4.dynamax_filter_ok",
            posterior_type=str(type(posterior)),
            posterior_attrs=attrs,
        )
        return True
    except Exception:
        logger.warning("smoke_test_m4.dynamax_falhou", traceback=traceback.format_exc())
        return False


def _smoke_test_jumpmodels() -> bool:
    try:
        import jumpmodels

        logger.info("smoke_test_m4.jumpmodels_import", file=jumpmodels.__file__)

        try:
            from jumpmodels.jump import JumpModel

            logger.info("smoke_test_m4.jumpmodels_jumpmodel_import_ok")
        except ImportError:
            import pkgutil

            submodules = [
                m.name for m in pkgutil.iter_modules(jumpmodels.__path__, prefix="jumpmodels.")
            ]
            logger.warning(
                "smoke_test_m4.jumpmodels_jumpmodel_import_falhou_listando_pacote",
                submodules=submodules,
            )
            raise

        import pandas as pd

        rng = np.random.default_rng(0)
        n = 200
        idx = pd.date_range("2024-01-01", periods=n, freq="D")
        x = pd.DataFrame({"f1": rng.normal(0, 1, n), "f2": rng.normal(0, 1, n)}, index=idx)

        model = JumpModel(n_components=3, jump_penalty=1.0, cont=True)
        model.fit(x, sort_by="cumret")
        labels = model.labels_
        attrs = [a for a in dir(model) if not a.startswith("_")][:20]
        logger.info(
            "smoke_test_m4.jumpmodels_fit_ok",
            labels_shape=str(getattr(labels, "shape", type(labels))),
            model_attrs=attrs,
        )
        return True
    except Exception:
        logger.warning("smoke_test_m4.jumpmodels_falhou", traceback=traceback.format_exc())
        return False


def main() -> int:
    logger.info("smoke_test_m4.inicio", python_version=sys.version)

    jax_ok = _smoke_test_jax()
    dynamax_ok = _smoke_test_dynamax() if jax_ok else False
    jumpmodels_ok = _smoke_test_jumpmodels()

    all_ok = jax_ok and dynamax_ok and jumpmodels_ok
    logger.info(
        "smoke_test_m4.resumo",
        jax_ok=jax_ok,
        dynamax_ok=dynamax_ok,
        jumpmodels_ok=jumpmodels_ok,
        todas_ok=all_ok,
    )
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
