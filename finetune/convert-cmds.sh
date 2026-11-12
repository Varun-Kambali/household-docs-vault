set -e
cd finetune/out
L=llama.cpp-src
export PYTHONPATH=$L/gguf-py
python $L/convert_hf_to_gguf.py merged --outfile vault-f16.gguf --outtype f16
python $L/convert_hf_to_gguf.py merged --mmproj --outfile mmproj-vault-f16.gguf --outtype f16
llama-quantize vault-f16.gguf vault-q4_k_m.gguf Q4_K_M
