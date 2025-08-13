import streamlit as st
from openai import OpenAI
from docx import Document
import tempfile
import os
from datetime import date
from pathlib import Path
import shutil

# --- Configuração da API ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("⚠️ API Key da OpenAI não encontrada.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
# --- Parametrização de áudio ---
from pydub import AudioSegment
from pathlib import Path
import tempfile

SEGUNDO_POR_PARTE = 600  # 10 minutos
TARGET_SR = 16000        # 16 kHz
BITRATE = "48k"          # MP3 leve

ALLOWED_TYPES = ["mp3", "m4a", "wav", "ogg"]

def converter_para_mp3_mono16k(caminho_entrada: str) -> str:
    """Converte qualquer áudio para MP3, 16 kHz, mono, bitrate baixo."""
    caminho_saida = Path(caminho_entrada).with_suffix("").as_posix() + "_proc.mp3"
    try:
        audio = AudioSegment.from_file(caminho_entrada)
        audio = audio.set_frame_rate(TARGET_SR).set_channels(1)
        audio.export(caminho_saida, format="mp3", bitrate=BITRATE)
        return caminho_saida
    except Exception as e:
        print(f"Erro ao converter áudio: {e}")
        return None

def duracao_segundos(caminho: str) -> float:
    """Retorna a duração do áudio em segundos."""
    try:
        audio = AudioSegment.from_file(caminho)
        return len(audio) / 1000  # pydub retorna duração em milissegundos
    except Exception:
        return 0.0

def fatiar_audio(path_mp3: str, segundos_por_parte: int = SEGUNDO_POR_PARTE) -> list:
    """
    Fatia o MP3 em partes de até `segundos_por_parte`.
    Retorna lista ordenada com caminhos das partes.
    """
    try:
        audio = AudioSegment.from_file(path_mp3)
        partes = []
        out_dir = Path(tempfile.mkdtemp(prefix="chunks_"))
        total_ms = len(audio)
        step_ms = segundos_por_parte * 1000

        for i, start in enumerate(range(0, total_ms, step_ms)):
            end = min(start + step_ms, total_ms)
            parte_audio = audio[start:end]
            caminho_parte = out_dir / f"parte_{i+1:03d}.mp3"
            parte_audio.export(caminho_parte, format="mp3", bitrate=BITRATE)
            partes.append(str(caminho_parte))

        # Se por algum motivo não segmentou, devolve o original
        if not partes:
            partes = [path_mp3]

        return partes
    except Exception as e:
        print(f"Erro ao fatiar áudio: {e}")
        return [path_mp3]


# -------- Transcrição (Whisper) --------
def transcrever_um_arquivo(caminho_audio: str) -> str:
    """Transcreve um arquivo individual com Whisper-1 e retorna texto."""
    with open(caminho_audio, "rb") as f:
        tr = client.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )
    return tr.text or ""

def transcrever_em_partes(partes: list) -> str:
    """Transcreve cada parte e concatena com separadores claros."""
    textos = []
    for idx, p in enumerate(partes, start=1):
        try:
            texto = transcrever_um_arquivo(p).strip()
            if texto:
                textos.append(f"[PARTE {idx}]\n{texto}")
        except Exception as e:
            st.warning(f"Falha ao transcrever a parte {idx}: {e}")
    return "\n\n".join(textos).strip()

# -------- App --------
st.title("🧠 Gerador de Relatório de Psicoterapia")

audio_file = st.file_uploader("🎤 Envie o áudio da sessão", type=ALLOWED_TYPES)
nome_paciente = st.text_input("🧍 Nome do Paciente")
idade_paciente = st.text_input("📅 Idade do Paciente")
numero_sessao = st.text_input("🔢 Número da Sessão")
nome_psicologo = st.text_input("👩‍⚕️ Acadêmico(a)")
nome_supervisor = st.text_input("🧑‍🏫 Supervisor(a)")
data_sessao = st.date_input("📅 Data da Sessão", value=date.today())

if st.button("🚀 Gerar Relatório") and audio_file:
    # 1) Salvar upload
    with st.spinner("Salvando arquivo..."):
        ext = os.path.splitext(audio_file.name)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp.write(audio_file.read())
            original_path = tmp.name

    # 2) Converter p/ MP3 leve (16kHz, mono) — reduz risco de 400/timeout
    with st.spinner("Convertendo áudio (16 kHz, mono, MP3)..."):
        mp3_path = converter_para_mp3_mono16k(original_path)
        if not mp3_path or not os.path.exists(mp3_path):
            st.stop()

    # 3) Fatiar se for longo
    with st.spinner("Verificando duração e fatiando, se necessário..."):
        dur = duracao_segundos(mp3_path)
        if dur > SEGUNDO_POR_PARTE:
            partes = fatiar_audio(mp3_path, SEGUNDO_POR_PARTE)
        else:
            partes = [mp3_path]

    # 4) Transcrever tudo
    with st.spinner("Transcrevendo áudio... ⏳"):
        try:
            texto_transcrito = transcrever_em_partes(partes)
            if not texto_transcrito:
                st.error("Transcrição ficou vazia.")
                st.stop()
        except Exception as e:
            st.error(f"Erro na transcrição: {e}")
            st.stop()

    # 5) Gerar relatório com GPT (sem mostrar a transcrição na tela)
    with st.spinner("Gerando relatório com IA... ✨"):
        prompt = f"""
Você é um psicólogo especializado em Terapia de Aceitação e Compromisso (ACT) e Terapia Cognitivo-Comportamental (TCC). Sua tarefa é ler a transcrição abaixo e gerar um relatório clínico detalhado seguindo o modelo a seguir. Use somente informações presentes na transcrição. Não invente dados, não preencha campos que não estejam claros.
Seja claro, objetivo e profissional. Escreva em português do Brasil.

Estruture exatamente neste formato:

REGISTRO DOCUMENTAL
Paciente: {nome_paciente}
Idade: {idade_paciente}
Data: {data_sessao.strftime('%d/%m/%Y')}    Sessão: {numero_sessao}
Acadêmicos: {nome_psicologo}
Supervisor: {nome_supervisor}

Estrutura do relatório:

Relato
[Descreva de forma objetiva e completa o principal relato do paciente na sessão, resumindo os pontos centrais abordados.]

Análise do Relato / Hipóteses iniciais
[Analise o conteúdo do relato considerando conceitos da ACT (valores, aceitação, defusão, atenção ao momento presente, self como contexto, ação comprometida) e da TCC (pensamentos automáticos, crenças centrais, esquemas). Aponte hipóteses clínicas iniciais baseadas no que o paciente expressa. Inclua observações sobre temas recorrentes, por exemplo, se o tema de solidão ou outro se intensifica no contexto.]

Exame do Estado Mental do Paciente

Estado emocional atual (última semana): [descrever]

Estado de saúde atual (última semana): [descrever]

Aspectos do paciente na entrevista: [descrever]

Comunicação com os estagiários: [descrever]

Sentimentos verbalizados ou demonstrados: [descrever]

Consciência: [descrever]

Conduta: [descrever]

Linguagem: [descrever]

Pensamento: [descrever]

Observações gerais
[Inclua aqui qualquer observação adicional relevante identificada na transcrição.]

Sugestões para o próximo atendimento
[Forneça recomendações práticas e objetivas para a próxima sessão, alinhadas à ACT e TCC, como exercícios, psicoeducação, práticas de mindfulness, registros de pensamentos, ou exploração de valores.]
=== TRANSCRIÇÃO COMPLETA ===
{texto_transcrito}
"""
        try:
            resposta = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )
            texto_relatorio = resposta.choices[0].message.content.strip()
        except Exception as e:
            st.error(f"Erro ao gerar relatório: {e}")
            st.stop()

    # 6) Montar DOCX: relatório + transcrição completa
    with st.spinner("Gerando DOCX... 📄"):
        doc = Document()

        # Relatório formatado (linha a linha preserva quebras)
        for linha in texto_relatorio.splitlines():
            doc.add_paragraph(linha)

        # Página nova + transcrição
        doc.add_page_break()
        doc.add_heading("Transcrição Completa", level=1)
        for linha in texto_transcrito.splitlines():
            doc.add_paragraph(linha)

        doc_path = tempfile.NamedTemporaryFile(delete=False, suffix=".docx").name
        doc.save(doc_path)

    with open(doc_path, "rb") as f:
        st.success("✅ Relatório gerado!")
        st.download_button(
            "📥 Baixar Relatório",
            f,
            file_name=f"Relatorio_{nome_paciente}.docx"
        )

    # Limpeza básica (opcional)
    try:
        # remove diretórios temporários usados na segmentação
        for p in Path(tempfile.gettempdir()).glob("chunks_*"):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass

