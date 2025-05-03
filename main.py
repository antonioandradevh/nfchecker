# python -m streamlit run main.py

import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
import zipfile
import tempfile
# DICIONARIO
from mapeamento_materiais import MATERIAL_MAPPING, NAO_EMBALAGENS

st.set_page_config(page_title="Validador de Notas Fiscais", page_icon="📄", layout="wide")

def processar_xml(xml_content, filename):
    try:
        ns = {'ns': 'http://www.portalfiscal.inf.br/nfe'}
        root = ET.fromstring(xml_content)
        infNFe = root.find('.//ns:infNFe', ns)

        dados = []

        for det in infNFe.findall('.//ns:det', ns):
            prod = det.find('.//ns:prod', ns)
            material = prod.find('ns:xProd', ns).text.upper().strip()
            quantidade = float(prod.find('ns:qCom', ns).text)
            unidade = prod.find('ns:uCom', ns).text.strip().lower()
            if 'ton' in unidade:
                quantidade *= 1000  # converter para kg
            valor_kg = float(prod.find('ns:vUnCom', ns).text)
            valor_venda = float(prod.find('ns:vProd', ns).text)
            numero_nota = int(infNFe.find('.//ns:ide/ns:nNF', ns).text.lstrip('0'))

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
                'Tipo NF': infNFe.find('.//ns:ide/ns:tpNF', ns).text,
                'ESTADO': infNFe.find('.//ns:emit/ns:enderEmit/ns:UF', ns).text,
                'COOPERATIVA': infNFe.find('.//ns:emit/ns:xNome', ns).text,
                'MÊS': infNFe.find('.//ns:ide/ns:dhEmi', ns).text[5:7],
                'CATEGORIA': categoria,
                'SUBCATEGORIA': subcategoria,
                'MATERIAL': material,
                'QUANTIDADE': quantidade if status == 'VALIDADO' else 0,
                'VALOR POR KG': valor_kg,
                'VALOR POR VENDA': valor_venda,
                'NOME DO ARQUIVO': str(numero_nota),
                'CNPJ DO COMPRADOR': infNFe.find('.//ns:dest/ns:CNPJ', ns).text,
                'UNIDADE': unidade,
                'NCM': prod.find('ns:NCM', ns).text,
                'CFOP': prod.find('ns:CFOP', ns).text,
                'SOBRA': '',
                'MÊS VALIDAÇÃO': '',
                'ANO DE EMISSÃO': infNFe.find('.//ns:ide/ns:dhEmi', ns).text[:4],
                'ANO TC': '',
                'PAULO/REC+': '',
                'MÊS ENTREGA': '',
                'CNPJ ORGANIZAÇÃO': infNFe.find('.//ns:emit/ns:CNPJ', ns).text,
                'CHAVE DE ACESSO': root.find('.//ns:protNFe/ns:infProt/ns:chNFe', ns).text,
                'STATUS': status,
                'NATUREZA': '',
                'OBSERVAÇÕES': observacoes,
                'QUANTIDADE NÃO VALIDADA': quantidade if status != 'VALIDADO' else 0,
                'PROGRAMA': ''
            }

            dados.append(dados_nota)

        return pd.DataFrame(dados)

    except Exception as e:
        st.error(f"Erro ao processar o arquivo {filename}: {e}")
        return pd.DataFrame()

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

    uploaded_files = st.file_uploader("Carregue os arquivos XML ou ZIP das notas fiscais", type=["xml", "zip"], accept_multiple_files=True)

    if uploaded_files:
        arquivos_xml = []
        for uploaded in uploaded_files:
            if uploaded.name.lower().endswith('.zip'):
                with zipfile.ZipFile(uploaded) as z:
                    for name in z.namelist():
                        if name.endswith('.xml'):
                            with z.open(name) as file:
                                arquivos_xml.append(BytesIO(file.read()))
            elif uploaded.name.lower().endswith('.xml'):
                arquivos_xml.append(uploaded)

        dfs = [processar_xml(file.getvalue(), '') for file in arquivos_xml if not processar_xml(file.getvalue(), '').empty]

        if dfs:
            df_final = pd.concat(dfs, ignore_index=True)
            st.subheader("Editar Dados Processados")
            edited_df = st.data_editor(df_final, num_rows="dynamic")

            st.subheader("Download do Excel")
            excel_data = to_excel(edited_df)
            st.download_button("📥 Baixar Resultados em Excel", data=excel_data, file_name="resultados_validacao.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.subheader("Resumo para E-mail")
            total_recebido = (edited_df['QUANTIDADE'] + edited_df['QUANTIDADE NÃO VALIDADA']).sum() / 1000
            total_validado = edited_df['QUANTIDADE'].sum() / 1000
            total_invalidado = edited_df['QUANTIDADE NÃO VALIDADA'].sum() / 1000
            percentual = (total_validado / total_recebido * 100) if total_recebido > 0 else 0

            resumo_linhas = [
                "RESUMO DA VALIDAÇÃO DE NOTAS FISCAIS",
                "",
                f"Total de arquivos processados: {len(arquivos_xml)}",
                f"Total Recebido: {total_recebido:,.2f} t",
                f"Total Validado: {total_validado:,.2f} t",
                f"Total Invalidado: {total_invalidado:,.2f} t",
                f"Percentual Validado: {percentual:.2f}%",
                "",
                "Quantitativo por Tipo de Material:"
            ]

            tipos = edited_df[edited_df['STATUS'] == 'VALIDADO'].groupby('CATEGORIA')['QUANTIDADE'].sum() / 1000
            for categoria, qtd in tipos.items():
                resumo_linhas.append(f"- {categoria}: {qtd:,.2f} t")

            resumo_linhas.append("\nNotas Fiscais Invalidas:")
            for _, row in edited_df[edited_df['STATUS'] == 'INVALIDADO'][['CHAVE DE ACESSO', 'OBSERVAÇÕES']].iterrows():
                resumo_linhas.append(f"- {row['CHAVE DE ACESSO']}: {row['OBSERVAÇÕES']}")

            resumo_linhas.append("\nDistribuição por Programa:")
            programas = edited_df.groupby('PROGRAMA')['QUANTIDADE'].sum() / 1000
            for programa, qtd in programas.items():
                resumo_linhas.append(f"- {programa or '(vazio)'}: {qtd:,.2f} t")

            resumo = "\n".join(resumo_linhas)

            st.text_area("Texto para copiar:", value=resumo, height=600)

if __name__ == "__main__":
    main()
