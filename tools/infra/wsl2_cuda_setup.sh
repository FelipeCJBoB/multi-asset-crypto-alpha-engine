#!/bin/bash
# Provisiona WSL2 (Ubuntu-22.04) para treino LightGBM real sob CUDA --
# RTX 4060 Ti / Ada Lovelace (sm_89). Roda DENTRO do WSL2, nunca no
# Windows (`wsl -d Ubuntu-22.04 -- bash tools/infra/wsl2_cuda_setup.sh`
# a partir do repo montado em /mnt/c/...).
#
# Reconstrói de forma reprodutível o que a sessão de 2026-08-29 fez à mão
# -- corrigindo, não repetindo, os 3 erros reais achados nessa sessão
# (`audit/architecture_gaps_log.yaml::AG-375/AG-376/AG-377`, ler antes de
# editar este script):
#
#   AG-375 -- libnccl2/libnccl-dev não têm dependência apt de nenhum
#   cuda-toolkit-* (confirmado via `apt-cache show`); instalar sem pin
#   pega a build MAIS RECENTE (hoje +cuda13.3), incompatível com um
#   toolkit mais antigo instalado ao lado -- `nvlink error: Uncompress
#   failed` no ÚLTIMO passo do build do LightGBM, sem nenhum aviso de
#   dependência quebrada. As duas versões abaixo são as DUAS METADES do
#   MESMO par -- nunca mude uma sem checar a outra via
#   `apt-cache madison libnccl2` primeiro.
#
#   AG-376/AG-377 -- `.venv/` dentro do repo é o MESMO caminho físico
#   NTFS visto pelo Windows nativo E pelo WSL2 via /mnt/c/... -- venv
#   Python é layout específico de SO (Linux usa symlinks POSIX tipo
#   lib64->lib que o driver NTFS do Windows não sabe apagar). `uv
#   sync`/`uv pip install` do WSL2 sem isolar o venv corrompe o ambiente
#   Windows. Corrigido isolando o venv WSL2 FORA da árvore do repo
#   (nunca alcançável via caminho Windows) -- e nunca usando `uv
#   run`/`uv sync` normal nesse venv depois de instalar o LightGBM CUDA
#   (`uv run` resincroniza contra uv.lock, que resolve pro wheel CPU do
#   PyPI, e reverte o build silenciosamente -- comportamento documentado
#   do uv, não bug; a alternativa nativa do uv pra isso,
#   `tool.uv.sources` com `extra`, tem bugs abertos upstream --
#   astral-sh/uv#17732/#17967 -- que arriscam derrubar dependência
#   transitiva da resolução DEFAULT, ou seja arriscam o caminho CPU/
#   Windows de produção real deste projeto para resolver um problema só
#   do ambiente GPU opcional -- por isso NÃO usado aqui).
#
# Idempotente -- seguro rodar de novo (cada passo checa se já foi feito).
set -euo pipefail

# --- par de versão travado (AG-375) ----------------------------------
CUDA_TOOLKIT_VERSION="12-6"          # cuda-toolkit-${CUDA_TOOLKIT_VERSION}
NCCL_VERSION="2.24.3-1+cuda12.6"     # DEVE casar exato com a linha acima
GPU_ARCH="89"                        # RTX 4060 Ti = Ada Lovelace = sm_89

# --- venv WSL2-nativo, fora da árvore do repo (AG-376/AG-377) --------
WSL_VENV_DIR="${HOME}/.venvs/binance-futures-cuda"
REPO_DIR="/mnt/c/Robo MT5 Forex/Cryptex/Binance_Futures"
UV_BIN="${HOME}/.local/bin/uv"

log() { echo ">> $*"; }

log "1/7: repo apt wsl-ubuntu (CUDA Toolkit -- driver via passthrough do host)"
if [ ! -f /etc/apt/sources.list.d/cuda-wsl-ubuntu-x86_64.list ]; then
    wget -q https://developer.download.nvidia.com/compute/cuda/repos/wsl-ubuntu/x86_64/cuda-keyring_1.1-1_all.deb -O /tmp/cuda-keyring-wsl.deb
    dpkg -i /tmp/cuda-keyring-wsl.deb
else
    log "   ja presente, pulando"
fi

log "2/7: repo apt ubuntu2204 (NCCL -- nao existe no repo wsl-ubuntu, AG-375)"
if [ ! -f /etc/apt/sources.list.d/cuda-ubuntu2204-x86_64.list ]; then
    wget -q https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb -O /tmp/cuda-keyring-u2204.deb
    dpkg-deb -x /tmp/cuda-keyring-u2204.deb /tmp/ncclrepo
    cp /tmp/ncclrepo/etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/cuda-ubuntu2204-x86_64.list
else
    log "   ja presente, pulando"
fi
apt-get update -qq

log "3/7: CUDA Toolkit ${CUDA_TOOLKIT_VERSION} + cmake"
apt-get -y install "cuda-toolkit-${CUDA_TOOLKIT_VERSION}" cmake

log "4/7: NCCL ${NCCL_VERSION} pinado (AG-375 -- nunca instalar sem versao) + hold contra apt upgrade"
apt-get -y --allow-downgrades install "libnccl2=${NCCL_VERSION}" "libnccl-dev=${NCCL_VERSION}"
apt-mark hold libnccl2 libnccl-dev

log "5/7: sanity check -- GPU precisa aparecer AQUI DENTRO do WSL2, nao so no host"
if ! nvidia-smi > /dev/null 2>&1; then
    echo "FALHOU: nvidia-smi nao ve a GPU dentro do WSL2 -- passthrough quebrado (driver do host desatualizado? reiniciar o WSL2 com 'wsl --shutdown' no PowerShell?). Parando aqui de proposito, nao adianta seguir." >&2
    exit 1
fi

log "6/7: uv + venv separado (${WSL_VENV_DIR}, AG-376/AG-377 -- NUNCA .venv/ dentro do repo)"
if [ ! -x "$UV_BIN" ]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi
# Persiste em ~/.bashrc (idempotente) -- um terminal WSL2 futuro que NAO
# rode este script de novo ainda assim nunca cai no .venv/ compartilhado.
BASHRC_LINE="export UV_PROJECT_ENVIRONMENT=\"${WSL_VENV_DIR}\""
if ! grep -qF "$BASHRC_LINE" "${HOME}/.bashrc" 2>/dev/null; then
    echo "" >> "${HOME}/.bashrc"
    echo "# AG-376/AG-377 (2026-08-29) -- nunca deixar uv sync/pip usar .venv/" >> "${HOME}/.bashrc"
    echo "# dentro do repo compartilhado com o Windows via /mnt/c/... (corrompe" >> "${HOME}/.bashrc"
    echo "# o venv Windows -- symlink POSIX que o driver NTFS nao apaga)." >> "${HOME}/.bashrc"
    echo "$BASHRC_LINE" >> "${HOME}/.bashrc"
fi
export UV_PROJECT_ENVIRONMENT="$WSL_VENV_DIR"
cd "$REPO_DIR"
"$UV_BIN" sync

log "7/7: LightGBM recompilado com USE_CUDA=ON (sm_${GPU_ARCH}), venv isolado"
export PATH="/usr/local/cuda/bin:${PATH}"
export CUDA_HOME=/usr/local/cuda
export VIRTUAL_ENV="$WSL_VENV_DIR"
"$UV_BIN" pip install lightgbm --no-binary lightgbm \
    --config-settings=cmake.define.USE_CUDA=ON \
    --config-settings=cmake.define.CMAKE_CUDA_ARCHITECTURES="${GPU_ARCH}" \
    --reinstall

echo ""
echo "=== Pronto. ==="
echo "NUNCA use 'uv run'/'uv sync' dentro de ${WSL_VENV_DIR} depois disto --"
echo "reverte o LightGBM de volta pro wheel CPU do PyPI silenciosamente"
echo "(AG-376). Para treinar/rodar sob GPU, chame o interpretador direto:"
echo ""
echo "  ${WSL_VENV_DIR}/bin/python -m src.models.hyperparams_optuna \\"
echo "      --symbol ETHUSDT --resolution-id R3 --variant camada1 \\"
echo "      --n-trials 3 --device-type cuda --scratch"
echo ""
echo "Reinstalar dependencias normais (numpy, polars, etc.) TAMBEM precisa"
echo "ser 'uv sync' (nunca 'uv run <algo>' puro) neste venv, senao o"
echo "LightGBM CUDA e revertido junto -- ou simplesmente rode este script"
echo "de novo (idempotente, passo 7 sempre reconstroi o CUDA por cima)."
