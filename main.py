# python -m streamlit run main.py

import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
import zipfile
import traceback

try:
    from mapeamento_materiais import MATERIAL_MAPPING, NAO_EMBALAGENS
except ImportError:
    MATERIAL_MAPPING = {}
    NAO_EMBALAGENS = {}

st.set_page_config(page_title="Validador de Notas Fiscais", page_icon="📄", layout="wide")

# --- FUNÇÃO AUXILIAR PARA EVITAR ERRO 'NONETYPE' ---
def get_text(element, tag_path, ns, default=None):
    """Tenta encontrar uma tag e retornar o texto. Retorna default se não encontrar."""
    if element is None:
        return default
    found = element.find(tag_path, ns)
    if found is not None and found.text is not None:
        return found.text
    return default

def processar_xml(xml_content, filename):
    """
    Retorna: (DataFrame com dados, Dicionário de erro ou None)
    """
    try:
        ns = {'ns': 'http://www.portalfiscal.inf.br/nfe'}
        
        # Tenta fazer o parse do XML
        try:
            root = ET.fromstring(xml_content)
        except ET.ParseError:
            return pd.DataFrame(), {"Arquivo": filename, "Erro": "Estrutura XML inválida ou corrompida."}

        # Verifica status da NFe (protNFe) se existir
        protNFe = root.find('.//ns:protNFe', ns)
        if protNFe:
            cStat = get_text(protNFe, './/ns:infProt/ns:cStat', ns)
            xMotivo = get_text(protNFe, './/ns:infProt/ns:xMotivo', ns)
            
            # Código 100 = Autorizado. Qualquer outro pode indicar problema (Denegada, Cancelada, etc)
            # Nota: Às vezes notas antigas ou de contingência podem variar, ajuste conforme necessidade.
            if cStat != '100':
                return pd.DataFrame(), {"Arquivo": filename, "Erro": f"Status Inválido ({cStat}): {xMotivo}"}

        # Busca infNFe
        infNFe = root.find('.//ns:infNFe', ns)
        if infNFe is None:
            # Pode ser um XML de evento, cancelamento ou inutilização, não uma NFe completa
            return pd.DataFrame(), {"Arquivo": filename, "Erro": "Tag <infNFe> não encontrada. O arquivo pode ser um evento ou recibo, não a nota fiscal completa."}

        dados = []

        # Itera sobre os produtos
        detalhes = infNFe.findall('.//ns:det', ns)
        if not detalhes:
            return pd.DataFrame(), {"Arquivo": filename, "Erro": "Nenhum produto (tag <det>) encontrado na nota."}

        # Dados do cabeçalho da nota
        ide = infNFe.find('.//ns:ide', ns)
        emit = infNFe.find('.//ns:emit', ns)
        dest = infNFe.find('.//ns:dest', ns)
        
        # Safe extractions para cabeçalho
        nNF_str = get_text(ide, 'ns:nNF', ns, '0')
        numero_nota = int(nNF_str.lstrip('0')) if nNF_str.isdigit() else 0
        data_emissao = get_text(ide, 'ns:dhEmi', ns, '')
        ano_emissao = data_emissao[:4] if len(data_emissao) >= 4 else ''
        mes_emissao = data_emissao[5:7] if len(data_emissao) >= 7 else ''
        
        # Chave de acesso
        chave_acesso = get_text(root, './/ns:protNFe/ns:infProt/ns:chNFe', ns, '')
        if not chave_acesso:
             # Tenta pegar do atributo ID se não tiver protocolo
             chave_acesso = infNFe.get('Id', '').replace('NFe', '')

        cnpj_emit = get_text(emit, 'ns:CNPJ', ns, '')
        nome_emit = get_text(emit, 'ns:xNome', ns, '')
        uf_emit = get_text(emit, 'ns:enderEmit/ns:UF', ns, '')
        cnpj_dest = get_text(dest, 'ns:CNPJ', ns, '')

        for det in detalhes:
            prod = det.find('.//ns:prod', ns)
            if prod is None: 
                continue

            material = get_text(prod, 'ns:xProd', ns, '').upper().strip()
            
            # Tratamento numérico seguro
            qCom_str = get_text(prod, 'ns:qCom', ns, '0')
            try:
                quantidade = float(qCom_str)
            except ValueError:
                quantidade = 0.0

            unidade = get_text(prod, 'ns:uCom', ns, '').strip().lower()
            if 'ton' in unidade:
                quantidade *= 1000  # converter para kg

            vUnCom_str = get_text(prod, 'ns:vUnCom', ns, '0')
            try:
                valor_kg = float(vUnCom_str)
            except ValueError:
                valor_kg = 0.0
                
            vProd_str = get_text(prod, 'ns:vProd', ns, '0')
            try:
                valor_venda = float(vProd_str)
            except ValueError:
                valor_venda = 0.0

            # Lógica de Mapeamento
            if material in NAO_EMBALAGENS:
                categoria, tipo_nao_embalagem = NAO_EMBALAGENS[material]
                subcategoria = ''
                status = 'INVALIDADO'
                observacoes = 'NÃO EMBALAGEM - ' + tipo_nao_embalagem
            elif material in MATERIAL_MAPPING:
                categoria, subcategoria = MATERIAL_MAPPING[material]
                status = 'VALIDADO'
                observacoes = ''
            else:
                categoria = ''
                subcategoria = ''
                status = 'VALIDADO'
                observacoes = ''

            dados_nota = {
                'Tipo NF': get_text(ide, 'ns:tpNF', ns),
                'ESTADO': uf_emit,
                'COOPERATIVA': nome_emit,
                'MÊS': mes_emissao,
                'CATEGORIA': categoria,
                'SUBCATEGORIA': subcategoria,
                'MATERIAL': material,
                'QUANTIDADE': quantidade if status == 'VALIDADO' else 0,
                'VALOR POR KG': valor_kg,
                'VALOR POR VENDA': valor_venda,
                'NOME DO ARQUIVO': filename, # Nome do arquivo incluso
                'NUMERO NOTA': numero_nota,
                'CNPJ DO COMPRADOR': cnpj_dest,
                'UNIDADE': unidade,
                'NCM': get_text(prod, 'ns:NCM', ns),
                'CFOP': get_text(prod, 'ns:CFOP', ns),
                'SOBRA': '',
                'MÊS VALIDAÇÃO': '',
                'ANO DE EMISSÃO': ano_emissao,
                'ANO TC': '',
                'PAULO/REC+': '',
                'MÊS ENTREGA': '',
                'CNPJ ORGANIZAÇÃO': cnpj_emit,
                'CHAVE DE ACESSO': chave_acesso,
                'STATUS': status,
                'NATUREZA': '',
                'OBSERVAÇÕES': observacoes,
                'QUANTIDADE NÃO VALIDADA': quantidade if status != 'VALIDADO' else 0,
                'PROGRAMA': ''
            }

            dados.append(dados_nota)

        return pd.DataFrame(dados), None

    except Exception as e:
        # Captura erro genérico de Python (código bugado)
        return pd.DataFrame(), {"Arquivo": filename, "Erro": f"Erro de processamento Python: {str(e)}"}

def to_excel(df):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Dados Completos')

        resumo = pd.DataFrame({
            'Métrica': [
                'Total Recebido',
                'Total Validado',
                'Total Invalidado',
                'Percentual Validado'
            ],
            'Valor': [
                df['QUANTIDADE'].sum(),
                df['QUANTIDADE'].sum(),
                df['QUANTIDADE NÃO VALIDADA'].sum(),
                f"{(df['QUANTIDADE'].sum() / (df['QUANTIDADE'].sum() + df['QUANTIDADE NÃO VALIDADA'].sum()) * 100):.2f}%" if (df['QUANTIDADE'].sum() + df['QUANTIDADE NÃO VALIDADA'].sum()) > 0 else '0.00%'
            ],
            'Unidade': ['kg', 'kg', 'kg', '']
        })
        resumo.to_excel(writer, index=False, sheet_name='Resumo')

        df_validado = df[df['STATUS'] == 'VALIDADO']
        if not df_validado.empty:
            por_tipo = df_validado.groupby('CATEGORIA')['QUANTIDADE'].sum().reset_index(name='QUANTIDADE')
            por_tipo.to_excel(writer, index=False, sheet_name='Validado por Tipo')

        df_invalidado = df[df['STATUS'] == 'INVALIDADO']
        if not df_invalidado.empty:
            df_invalidado[['CHAVE DE ACESSO', 'OBSERVAÇÕES']].to_excel(writer, index=False, sheet_name='Notas Invalidas')

        por_programa = df.groupby('PROGRAMA')['QUANTIDADE'].sum().reset_index()
        por_programa.to_excel(writer, index=False, sheet_name='Por Programa')

    return output.getvalue()

def main():
    st.title("📄 Sistema de Validação de Notas Fiscais")
    st.markdown("---")

    uploaded_files = st.file_uploader("Carregue os arquivos XML ou ZIP", type=["xml", "zip"], accept_multiple_files=True)

    if uploaded_files:
        arquivos_para_processar = []
        
        # Barra de progresso para descompactação
        with st.spinner('Lendo arquivos...'):
            for uploaded in uploaded_files:
                if uploaded.name.lower().endswith('.zip'):
                    try:
                        with zipfile.ZipFile(uploaded) as z:
                            for name in z.namelist():
                                if name.lower().endswith('.xml'):
                                    # Passamos o caminho completo dentro do zip como nome
                                    caminho_completo = f"{uploaded.name}/{name}"
                                    arquivos_para_processar.append((z.read(name), caminho_completo))
                    except zipfile.BadZipFile:
                        st.error(f"O arquivo {uploaded.name} parece estar corrompido.")
                elif uploaded.name.lower().endswith('.xml'):
                    arquivos_para_processar.append((uploaded.getvalue(), uploaded.name))

        if arquivos_para_processar:
            dfs = []
            erros = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            total_arquivos = len(arquivos_para_processar)

            for i, (conteudo, nome_arquivo) in enumerate(arquivos_para_processar):
                # Atualiza barra
                progress = (i + 1) / total_arquivos
                progress_bar.progress(progress)
                status_text.text(f"Processando {i+1}/{total_arquivos}: {nome_arquivo}")
                
                df_temp, erro = processar_xml(conteudo, nome_arquivo)
                
                if erro:
                    erros.append(erro)
                
                if not df_temp.empty:
                    dfs.append(df_temp)
            
            progress_bar.empty()
            status_text.empty()

            # --- EXIBIÇÃO DE ERROS ---
            if erros:
                st.error(f"Foram encontrados problemas em {len(erros)} arquivos.")
                df_erros = pd.DataFrame(erros)
                with st.expander("❌ Ver Relatório de Arquivos com Erro (Clique para expandir)", expanded=True):
                    st.dataframe(df_erros, use_container_width=True)
                    
                    # Botão para baixar relatório de erros
                    csv_erros = df_erros.to_csv(index=False).encode('utf-8')
                    st.download_button(
                        "📥 Baixar Relatório de Erros (CSV)",
                        data=csv_erros,
                        file_name="relatorio_erros_leitura.csv",
                        mime="text/csv"
                    )

            # --- EXIBIÇÃO DE SUCESSO ---
            if dfs:
                df_final = pd.concat(dfs, ignore_index=True)
                st.success(f"Processamento concluído! {len(df_final)} itens extraídos com sucesso.")
                
                st.subheader("Editar Dados Processados")
                edited_df = st.data_editor(df_final, num_rows="dynamic")

                st.subheader("Download e Resumo")
                excel_data = to_excel(edited_df)
                
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.download_button(
                        "📥 Baixar Resultados em Excel", 
                        data=excel_data, 
                        file_name="resultados_validacao.xlsx", 
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )

                # ... (Bloco de Resumo para Email permanece igual) ...
                total_recebido = (edited_df['QUANTIDADE'] + edited_df['QUANTIDADE NÃO VALIDADA']).sum() / 1000
                total_validado = edited_df['QUANTIDADE'].sum() / 1000
                total_invalidado = edited_df['QUANTIDADE NÃO VALIDADA'].sum() / 1000
                percentual = (total_validado / total_recebido * 100) if total_recebido > 0 else 0

                # ... (O código anterior continua igual até a linha onde definimos 'resumo_linhas') ...

                resumo_linhas = [
                    "RESUMO DA VALIDAÇÃO",
                    "",
                    f"Arquivos lidos com sucesso: {len(dfs)} (de {total_arquivos})",
                    f"Arquivos com erro de leitura: {len(erros)}",
                    f"Total Recebido (Bruto): {total_recebido:,.2f} t",
                    f"Total Validado (Embalagens): {total_validado:,.2f} t",
                    f"Percentual Validado: {percentual:.2f}%",
                    "",
                    "Quantitativo por Tipo (Validados):"
                ]
                
                # Lista os tipos validados
                tipos = edited_df[edited_df['STATUS'] == 'VALIDADO'].groupby('CATEGORIA')['QUANTIDADE'].sum() / 1000
                for categoria, qtd in tipos.items():
                    resumo_linhas.append(f"- {categoria}: {qtd:,.2f} t")
                
                # --- AQUI ESTA A PARTE QUE TINHA SUMIDO ---
                # Filtra apenas o que foi INVALIDADO (Não Embalagem ou fora do mapping)
                df_invalidados = edited_df[edited_df['STATUS'] == 'INVALIDADO']
                
                if not df_invalidados.empty:
                    resumo_linhas.append("\n--------------------------------")
                    resumo_linhas.append("DETALHAMENTO DE ITENS INVALIDADOS / NÃO EMBALAGEM:")
                    
                    # Itera sobre as linhas invalidadas para mostrar no texto
                    for _, row in df_invalidados[['CHAVE DE ACESSO', 'MATERIAL', 'OBSERVAÇÕES']].iterrows():
                        # Formata: Chave - Material - Motivo
                        resumo_linhas.append(f"- Nota: {row['CHAVE DE ACESSO']}")
                        resumo_linhas.append(f"  Item: {row['MATERIAL']}")
                        resumo_linhas.append(f"  Motivo: {row['OBSERVAÇÕES']}")
                        resumo_linhas.append("") # Linha em branco para separar
                # ------------------------------------------

                resumo = "\n".join(resumo_linhas)
                
                with col2:
                    st.text_area("Resumo para E-mail:", value=resumo, height=500)

            elif not erros:
                st.warning("Nenhum dado válido foi encontrado nos arquivos enviados.")

if __name__ == "__main__":
    main()
