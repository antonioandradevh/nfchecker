# python -m streamlit run main.py

import streamlit as st
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from mapeamento_materiais import MATERIAL_MAPPING, NAO_EMBALAGENS

st.set_page_config(page_title="Validador de Notas Fiscais", page_icon="📄", layout="wide")

def processar_xml(xml_content, filename):
    try:
        ns = {'ns': 'http://www.portalfiscal.inf.br/nfe'}
        root = ET.fromstring(xml_content)
        infNFe = root.find('.//ns:infNFe', ns)

        material = infNFe.find('.//ns:det/ns:prod/ns:xProd', ns).text.upper().strip()
        quantidade = float(infNFe.find('.//ns:det/ns:prod/ns:qCom', ns).text)
        valor_kg = float(infNFe.find('.//ns:det/ns:prod/ns:vUnCom', ns).text)
        valor_venda = float(infNFe.find('.//ns:det/ns:prod/ns:vProd', ns).text)

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
            'NOME DO ARQUIVO': filename,
            'CNPJ DO COMPRADOR': infNFe.find('.//ns:dest/ns:CNPJ', ns).text,
            'UNIDADE': infNFe.find('.//ns:det/ns:prod/ns:uCom', ns).text,
            'NCM': infNFe.find('.//ns:det/ns:prod/ns:NCM', ns).text,
            'CFOP': infNFe.find('.//ns:det/ns:prod/ns:CFOP', ns).text,
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

        return pd.DataFrame([dados_nota])

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
                df['QUANTIDADE'].sum() + df['QUANTIDADE NÃO VALIDADA'].sum(),
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

    uploaded_files = st.file_uploader("Carregue os arquivos XML das notas fiscais", type=["xml"], accept_multiple_files=True)

    if uploaded_files:
        dfs = [processar_xml(file.getvalue(), file.name) for file in uploaded_files if not processar_xml(file.getvalue(), file.name).empty]
        if dfs:
            df_final = pd.concat(dfs, ignore_index=True)
            st.subheader("Editar Dados Processados")
            edited_df = st.data_editor(df_final, num_rows="dynamic")

            st.subheader("Download do Excel")
            excel_data = to_excel(edited_df)
            st.download_button("📥 Baixar Resultados em Excel", data=excel_data, file_name="resultados_validacao.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

            st.subheader("Resumo para E-mail")
            resumo = f"""RESUMO DA VALIDAÇÃO DE NOTAS FISCAIS\n\nTotal de arquivos processados: {len(uploaded_files)}\nTotal Recebido: {edited_df['QUANTIDADE'].sum() + edited_df['QUANTIDADE NÃO VALIDADA'].sum():,.2f} kg\nTotal Validado: {edited_df['QUANTIDADE'].sum():,.2f} kg\nTotal Invalidado: {edited_df['QUANTIDADE NÃO VALIDADA'].sum():,.2f} kg\nPercentual Validado: {(edited_df['QUANTIDADE'].sum() / (edited_df['QUANTIDADE'].sum() + edited_df['QUANTIDADE NÃO VALIDADA'].sum()) * 100 if (edited_df['QUANTIDADE'].sum() + edited_df['QUANTIDADE NÃO VALIDADA'].sum()) > 0 else 0):.2f}%\n\nQuantitativo por Tipo de Material:\n"""
            tipos = edited_df[edited_df['STATUS'] == 'VALIDADO'].groupby('CATEGORIA')['QUANTIDADE'].sum()
            for categoria, qtd in tipos.items():
                resumo += f"- {categoria}: {qtd:,.2f} kg\n"

            resumo += "\nNotas Fiscais Invalidas:\n"
            for _, row in edited_df[edited_df['STATUS'] == 'INVALIDADO'][['CHAVE DE ACESSO', 'OBSERVAÇÕES']].iterrows():
                resumo += f"- {row['CHAVE DE ACESSO']}: {row['OBSERVAÇÕES']}\n"

            resumo += "\nDistribuição por Programa:\n"
           

            st.text_area("Texto para copiar:", value=resumo, height=600)

if __name__ == "__main__":
    main()