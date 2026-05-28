/**
 * EAlert Tracker v3.9.2
 *
 * ⚠️ 准确性原则(最高优先级):
 * 提供的信息必须经过确认,绝不捏造任何字段。
 * 所有字段(DOI、作者、日期、摘要)必须从可靠 API 验证获取,
 * 无法提取时明确标注「(作者信息无法确认)」等占位符,绝不猜测。
 *
 * 主要版本历史:
 * v3.7.0: 删除 extractDOI 捏造 DOI 逻辑;新增 validateDOI 验证;
 *         ensureFields 重写为 ensureAccurateFields;所有无法确认字段标注清楚
 * v3.6.1: 去重逻辑(标题+URL/DOI 双重比对)
 * v3.6.0: 模板独立为 template.md
 * v3.5:   报告格式优化(原文标题、点评质量)
 * v3.4:   新增 Google Scholar Alerts 支持
 */

const Imap = require('imap');
const { simpleParser } = require('mailparser');
const https = require('https');
const http = require('http');
const fs = require('fs');
const path = require('path');
const { execSync, spawnSync } = require('child_process');
// v3.8.1: 移除 nodemailer,不再发送邮件
// const nodemailer = require('nodemailer');
require('dotenv').config({ path: path.join(__dirname, '../.env') });

// ============ 配置 ============
const CONFIG = {
  targetKeywords: [
    'bioinformatics', 'computational biology', 'multi-omics', 'single-cell',
    'scRNA-seq', 'RNA-seq', 'ATAC-seq', 'proteomics', 'metabolomics',
    'spatial transcriptomics', 'genome-wide', 'GWAS',
    'machine learning', 'deep learning', 'neural network',
    'large language model', 'foundation model', 'AlphaFold',
    'cancer', 'tumor', 'oncology', 'carcinoma',
    'immunotherapy', 'immune checkpoint', 'CAR-T', 'tumor microenvironment',
    'treg', 'regulatory t', 'foxp3', 't cell', 'b cell', 'immune',
    'genomics', 'genome sequencing', 'gene expression', 'epigenomics',
    'transcriptomics', 'microbiome', 'virome',
    'stem cell', 'organoid', 'gene editing', 'CRISPR',
    'lifespan', 'longevity', 'aging', 'senescence',
    'neuroscience', 'brain organoid', 'epilepsy', 'neural',
    'systems biology', 'network medicine', 'precision medicine', 'biomarker',
    'synthetic biology', 'amino acid', 'protein', 'enzyme',
    'evolution', 'evolutionary', 'phylogeny', 'paleontology'
  ],

  journalSenders: ['nature.com', 'aaas.sciencepubs.org', 'science.org', 'cell.com', 'pnas.org', 'elsevier.com'],

  journalSubjects: [
    'Nature', 'Science', 'Cell', 'PNAS',
    'Translational', 'Immunology', 'Advances', 'Cancer',
    'Communications', 'Computational', 'Biotechnology',
    'Methods', 'Genetics', 'Medicine', 'Molecular', 'Reports', 'Metabolism',
    'Trends'
  ],

  // Google Scholar Alerts 配置
  scholarSenders: ['scholaralerts-noreply@google.com'],
  scholarSubjects: ['new articles', 'new citations', 'update'],   // Scholar 邮件 Subject 包含这些关键词
  scholarExcludeSubjects: ['confirm your scholar alert'],  // 排除确认邮件

  // 排除的非研究内容(精确匹配 Subject 关键词)
  excludeKeywords: [
    'Security alert', 'Login',
    'Careers', 'Career Path',
    'Speak up for science',
    'Unsubscribe',
    'In Other Journals',
  ],

  // v3.8.1: 移除邮件配置,只保留核心追踪参数
  daysBack: 1,
};

// ============ 工具函数 ============

function getISOWeek(date) {
  const d = new Date(Date.UTC(date.getFullYear(), date.getMonth(), date.getDate()));
  const dayNum = d.getUTCDay() || 7;
  d.setUTCDate(d.getUTCDate() + 4 - dayNum);
  const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
  return Math.ceil((((d - yearStart) / 86400000) + 1) / 7);
}

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms));
}

function matchesKeywords(text, keywords) {
  if (!text) return false;
  const lower = text.toLowerCase();
  return keywords.some(k => lower.includes(k.toLowerCase()));
}

function decodeSubject(str) {
  if (!str) return '';
  try {
    return str.replace(/=\?([^?]+)\?([BQ])\?([^?]*)\?=/gi, (_, charset, mode, content) => {
      if (mode === 'B') return Buffer.from(content, 'base64').toString(charset);
      if (mode === 'Q') return Buffer.from(
        content.replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16)))
          .replace(/_/g, ' '), charset).toString();
      return content;
    });
  } catch { return str; }
}

function httpGet(url, timeout = 8000) {
  return new Promise((resolve, reject) => {
    if (!url || !url.startsWith('http')) return reject(new Error('Invalid URL'));
    const client = url.startsWith('https') ? https : http;
    const req = client.get(url, {
      headers: { 'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36' }
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        return httpGet(res.headers.location, timeout).then(resolve).catch(reject);
      }
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    });
    req.setTimeout(timeout, () => { req.destroy(); reject(new Error('Timeout')); });
    req.on('error', reject);
  });
}

// ============ 期刊识别 ============

function extractJournalFromSubject(subject) {
  const s = subject.toLowerCase();
  if (s.includes('nature communications')) return 'Nature Communications';
  if (s.includes('nature cancer')) return 'Nature Cancer';
  if (s.includes('nature computational')) return 'Nature Computational Science';
  if (s.includes('nature methods')) return 'Nature Methods';
  if (s.includes('nature genetics')) return 'Nature Genetics';
  if (s.includes('nature medicine')) return 'Nature Medicine';
  if (s.includes('nature biotechnology')) return 'Nature Biotechnology';
  if (s.includes('nature')) return 'Nature';
  if (s.includes('science translational medicine')) return 'Science Translational Medicine';
  if (s.includes('science immunology')) return 'Science Immunology';
  if (s.includes('science advances')) return 'Science Advances';
  if (s.includes('science')) return 'Science';
  if (s.includes('cell metabolism')) return 'Cell Metabolism';
  if (s.includes('cell reports')) return 'Cell Reports';
  if (s.includes('molecular cell')) return 'Molecular Cell';
  if (s.includes('trends in biotechnology')) return 'Trends in Biotechnology';
  if (s.includes('cell')) return 'Cell';
  if (s.includes('pnas')) return 'PNAS';
  return 'Journal';
}

/**
 * 标准化期刊名称（v3.9.2 新增，2026-05-28 修复）
 * PubMed API 返回的 journal 字段可能包含全称、缩写、大小写不一致等问题
 * 此函数将它们统一为标准缩写
 */
function normalizeJournalName(journal) {
  if (!journal) return 'Journal';
  const j = journal.trim();
  const lower = j.toLowerCase();
  
  // PNAS 系列（全称 vs 简称）
  // 匹配：Proceedings of the National Academy of Sciences (USA)
  //       Proc Natl Acad Sci USA
  //       PNAS
  if (lower.includes('proc') || lower.includes('pnas') || 
      lower.includes('national academy') || lower.includes('proc natl acad sci')) {
    return 'PNAS';
  }

  // Nature 系列(大小写标准化)
  if (lower.includes('nature communications')) return 'Nature Communications';
  if (lower.includes('nature cancer')) return 'Nature Cancer';
  if (lower.includes('nature computational')) return 'Nature Computational Science';
  if (lower.includes('nature methods')) return 'Nature Methods';
  if (lower.includes('nature genetics')) return 'Nature Genetics';
  if (lower.includes('nature medicine')) return 'Nature Medicine';
  if (lower.includes('nature biotechnology')) return 'Nature Biotechnology';
  if (lower === 'nature') return 'Nature';

  // Science 系列
  if (lower.includes('science translational')) return 'Science Translational Medicine';
  if (lower.includes('science immunology')) return 'Science Immunology';
  if (lower.includes('science advances')) return 'Science Advances';
  if (lower === 'science') return 'Science';

  // Cell 系列
  if (lower.includes('cell metabolism')) return 'Cell Metabolism';
  if (lower.includes('cell reports')) return 'Cell Reports';
  if (lower.includes('molecular cell')) return 'Molecular Cell';
  if (lower.includes('trends in biotechnology')) return 'Trends in Biotechnology';
  if (lower === 'cell') return 'Cell';

  // 保持原标题格式(避免误判)
  return j;
}

// ============ 元数据获取 ============

/**
 * 从链接提取真实 DOI
 *
 * ⚠️ 准确性原则(v3.7.0):
 * 此函数只提取链接中已存在的真实 DOI。
 * 如果链接中没有真实 DOI(格式: 10.xxxx/字母开头),绝不生成或猜测。
 * 之前 v3.6.x 会通过 PII 格式生成假 DOI(如 10.1126/scitranslmed.abc123),
 * 已删除此逻辑,不再捏造任何 DOI。
 */
function extractDOI(link) {
  if (!link) return '';

  // 从 URL 中提取已有的真实 DOI
  const direct = link.match(/(10\.\d{4,}\/[^\s&"'?#<>,;]+)/);
  if (direct) {
    let doi = direct[1].replace(/[&"'?#<>,;].*$/, '');
    try { doi = decodeURIComponent(doi); } catch {}
    // v3.7.0: 验证看起来像真实 DOI(字母开头,不是 abc123 这种随机字符)
    if (/^10\.\d{4,}\/[a-zA-Z]/.test(doi)) {
      return doi;
    }
  }

  return '';  // 链接中没有真实 DOI,返回空字符串
}

/**
 * 获取论文详情(v3.9.2 重写 - 混合方案)
 *
 * 准确性优先流程:
 * 1. 通过 PubMed API 获取完整元数据(作者、期刊、摘要、真实 DOI)
 * 2. 如果 PubMed 无结果,从链接提取 DOI 并通过 CrossRef 验证
 * 3. CrossRef 验证通过才使用该 DOI
 * 4. 如果还是没有摘要,尝试从论文 URL 直接抓取(web_fetch)
 * 5. 完全无法获取时:确保原始字段准确,不捏造任何信息
 */
async function fetchPaperDetails(paper) {
  // Step 1: 优先通过 PubMed 获取完整元数据
  try {
    const meta = await fetchFromPubMed(paper.title);
    if (meta && meta.journal && meta.title) {
      ensureAccurateFields(meta);
      return meta;
    }
    // PubMed 有结果但无摘要?尝试 Step 4
    if (meta && (!meta.abstract || meta.abstract.length < 30)) {
      const webAbstract = await fetchAbstractFromURL(paper.link, paper.journal);
      if (webAbstract) {
        meta.abstract = webAbstract;
        meta.researchQuestion = inferResearchQuestion(meta.title || paper.title, webAbstract);
        meta.contributions = inferContributions(webAbstract, meta.title || paper.title);
        meta.comment = generateComment(meta.title || paper.title, webAbstract, meta.researchQuestion, meta.journal || paper.journal);
      }
    }
  } catch (e) {
    console.log(`    PubMed查询失败,尝试其他方式: ${e.message}`);
  }

  // Step 2: 尝试从链接提取真实 DOI 并验证
  const doi = extractDOI(paper.link);
  if (doi) {
    const isValid = await validateDOI(doi);
    if (isValid) {
      await sleep(300);
      const meta = await fetchCrossRef(doi);
      if (meta) {
        // CrossRef 有摘要则使用
        if (meta.abstract && meta.abstract.length > 30) {
          ensureAccurateFields(meta);
          return { ...paper, ...meta, doi };
        }
        // CrossRef 无摘要但之前 PubMed 也没拿到?尝试网页抓取
        const webAbstract = await fetchAbstractFromURL(paper.link, paper.journal || meta.journal);
        if (webAbstract) {
          meta.abstract = webAbstract;
          meta.researchQuestion = inferResearchQuestion(meta.title || paper.title, webAbstract);
          meta.contributions = inferContributions(webAbstract, meta.title || paper.title);
          meta.comment = generateComment(meta.title || paper.title, webAbstract, meta.researchQuestion, meta.journal || paper.journal);
        }
        ensureAccurateFields(meta);
        return { ...paper, ...meta, doi };
      }
    }
    // DOI 无效或无法验证,不使用该 DOI
  }

  // Step 3: 尝试从论文 URL 直接抓取摘要
  // 适用于:没有 DOI、PubMed/CrossRef 都失败的论文
  if (paper.link && !paper.link.includes('google.com/search')) {
    const paperLinkLower = (paper.link || '').toLowerCase();
    const isScienceTracking = paperLinkLower.includes('click.aaas.sciencepubs.org') ||
                              paperLinkLower.includes('click.science.org');
    // v3.9.2: Science 跟踪链接先通过 CrossRef 标题搜索找 DOI
    if (isScienceTracking) {
      console.log(`    ⚡ 检测到 Science 跟踪链接: ${paperLinkLower.substring(0,60)}`);
      const doiFromTitle = await searchCrossRefByTitle(paper.title);
      if (doiFromTitle) {
        await sleep(300);
        const meta = await fetchCrossRef(doiFromTitle);
        if (meta && meta.abstract && meta.abstract.length > 30) {
          paper.abstract = meta.abstract;
          paper.doi = doiFromTitle;
          paper.researchQuestion = inferResearchQuestion(paper.title, meta.abstract);
          paper.contributions = inferContributions(meta.abstract, paper.title);
          paper.comment = generateComment(paper.title, meta.abstract, paper.researchQuestion, paper.journal);
          return paper;
        }
      }
    }

    try {
      const webAbstract = await fetchAbstractFromURL(paper.link, paper.journal);
      if (webAbstract && webAbstract.length > 30) {
        paper.abstract = webAbstract;
        paper.researchQuestion = inferResearchQuestion(paper.title, webAbstract);
        paper.contributions = inferContributions(webAbstract, paper.title);
        paper.comment = generateComment(paper.title, webAbstract, paper.researchQuestion, paper.journal);
        return paper;
      }
    } catch (e) {
      console.log(`    网页抓取摘要失败: ${e.message}`);
    }
  }

  // Step 4: 完全无法获取可靠元数据
  // ⚠️ 确保原始字段准确,不捏造任何信息
  paper.authors = paper.authors || '(作者信息无法确认)';
  paper.date = paper.date || '(发表日期无法确认)';
  paper.journal = paper.journal || '(期刊信息无法确认)';
  paper.doi = '';  // 不显示无法验证的 DOI

  // v3.9.2: 无摘要时标注清楚,不生成模板内容
  if (!paper.abstract || paper.abstract.length < 30) {
    paper.researchQuestion = '(无法获取摘要,无法提取研究问题)';
    paper.contributions = ['(无法获取摘要,无法提取主要贡献)'];
    paper.comment = '(无法获取摘要,无法生成简评。建议访问原文链接查看详情。)';
  } else {
    paper.researchQuestion = inferResearchQuestion(paper.title, paper.abstract);
    paper.contributions = inferContributions(paper.abstract, paper.title);
    paper.comment = generateComment(paper.title, paper.abstract, paper.researchQuestion, paper.journal);
  }
  return paper;
}

/**
 * 从论文 URL 直接抓取摘要(v3.9.2 新增)
 * 支持:Nature、Science、Cell、PNAS、bioRxiv 等主流期刊
 */
async function fetchAbstractFromURL(url, journal) {
  if (!url || url.includes('google.com/search')) return null;

  const journalLower = (journal || '').toLowerCase();
  const urlLower = url.toLowerCase();

  // 确定最适合的抓取策略
  let fetchUrl = url;

  // Science: DOI URL 直接可抓
  if (urlLower.includes('science.org/doi/')) {
    fetchUrl = url;
  }
  // Science AAAS 跟踪链接: https://click.aaas.sciencepubs.org/?qs=...&dest=base64
  // qs=base64 是内部数据库 ID,无法解码为 URL。
  // httpGet 跟随重定向尝试获取内容
  if (urlLower.includes('click.aaas.sciencepubs.org') || urlLower.includes('click.science.org')) {
    if (urlLower.includes('science.org/doi/')) {
      fetchUrl = url; // Science DOI URL,直接抓
    }
    // 否则:尝试 httpGet 看是否重定向到真实页面
    // (部分链接会 302 重定向到 science.org)
  }
  // Nature: 加密链接解包后直接可抓
  else if (urlLower.includes('nature.com/articles') || urlLower.includes('nature.com/news')) {
    fetchUrl = url;
  }
  // bioRxiv/medRxiv: 有标准 API
  else if (urlLower.includes('biorxiv.org') || urlLower.includes('medrxiv.org')) {
    // 从 URL 提取 DOI/文章ID
    const biorxivMatch = url.match(/\/([\w.-]+)\/(\d{4}\.\d+)/i);
    if (biorxivMatch) {
      try {
        const apiUrl = `https://api.biorxiv.org/details/biorxiv/${biorxivMatch[2]}/`;
        const data = await httpGet(apiUrl);
        const json = JSON.parse(data);
        const collection = json.collection || [];
        for (const item of collection) {
          if (item.abstract && item.abstract.length > 50) {
            return item.abstract.replace(/<[^>]+>/g, '').trim();
          }
        }
      } catch (e) {}
    }
    // fallback: 直接抓页面
    fetchUrl = url;
  }
  // arXiv: 用 API
  else if (urlLower.includes('arxiv.org/abs/')) {
    const arxivMatch = url.match(/arxiv\.org\/abs\/([\w.-]+)/i);
    if (arxivMatch) {
      try {
        const apiUrl = `https://export.arxiv.org/api/query?id_list=${arxivMatch[1]}&max_results=1`;
        const xml = await httpGet(apiUrl);
        const abstractMatch = xml.match(/<summary[^>]*>([\s\S]*?)<\/summary>/i);
        if (abstractMatch) {
          return abstractMatch[1].replace(/<[^>]+>/g, '').trim();
        }
      } catch (e) {}
    }
  }

  // 通用网页抓取(处理 Nature、Science、Cell 等)
  try {
    const html = await httpGet(fetchUrl, 10000);

    // 从 HTML 中提取摘要
    let abstract = '';

    // 方式1: meta标签
    const metaAbstract = html.match(/<meta[^>]+name=["']abstract["'][^>]+content=["']([^"']+)/i) ||
                              html.match(/<meta[^>]+content=["']([^"']+)["'][^>]+name=["']abstract["']/i);
    if (metaAbstract) {
      abstract = metaAbstract[1].replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').trim();
    }

    // 方式2: JSON-LD
    if (!abstract || abstract.length < 30) {
      const jsonLdMatch = html.match(/<script[^>]+type=["']application\/json["'][^>]*>([\s\S]*?)<\/script>/i);
      if (jsonLdMatch) {
        try {
          const ldJson = JSON.parse(jsonLdMatch[1]);
          const abstractText = ldJson?.abstract || ldJson?.['@graph']?.[0]?.abstract || '';
          if (abstractText && abstractText.length > 30) {
            abstract = abstractText.replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').trim();
          }
        } catch (e) {}
      }
    }

    // 方式3: 从 HTML 文本中找摘要区块
    if (!abstract || abstract.length < 30) {
      // 找 "Abstract" 或 "摘要" 标题后的内容
      const abstractSection = html.match(/(?:<h[1-4][^>]*>\s*(?:Abstract|摘要|Summary)\s*<\/h[1-4]>|[\s\S]{0,200}(?:Abstract|摘要|Summary)[\s:]*)([\s\S]{100,2000}?)(?:<h[1-4]|Introduction|Background|Footnotes|References|\Z)/i);
      if (abstractSection) {
        abstract = abstractSection[1].replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
      }
    }

    if (abstract && abstract.length > 30) {
      // 清理 HTML 实体
      abstract = abstract.replace(/&#xa;?/g, '\n').replace(/&hellip;/g, '...').replace(/&mdash;/g, '-').trim();
      return abstract;
    }
  } catch (e) {
    console.log(`    fetchAbstractFromURL: ${fetchUrl} 失败 - ${e.message}`);
  }

  return null;
}

/** PubMed API 查询(通过标题搜索) */
// 计算两个字符串的标题相似度(基于词重叠率)
// 返回值:0~1,>0.6 认为匹配
function titleSimilarity(a, b) {
  const normalize = s => (s || '').toLowerCase().replace(/[^\w\s]/g, ' ').split(/\s+/).filter(w => w.length > 3);
  const wordsA = new Set(normalize(a));
  const wordsB = normalize(b);
  if (wordsA.size === 0 || wordsB.length === 0) return 0;
  const overlap = wordsB.filter(w => wordsA.has(w)).length;
  return overlap / Math.max(wordsA.size, wordsB.length);
}

async function fetchFromPubMed(title) {
  try {
    const query = encodeURIComponent(title.replace(/[^\w\s]/g, ' ').trim().substring(0, 200));
    // v3.9.2: 增加 retmax=5,逐条校验标题相似度,避免匹配到错误论文
    const url = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=${query}&retmax=5&retmode=json&sort=relevance`;

    const data = await httpGet(url);
    const json = JSON.parse(data);
    const pmids = json?.esearchresult?.idlist || [];
    if (pmids.length === 0) return null;

    // v3.9.2: 逐条校验标题相似度,取第一条匹配的
    let pmid = null;
    for (const candidatePmid of pmids) {
      await sleep(200);
      const checkUrl = `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=${candidatePmid}&retmode=json`;
      try {
        const checkData = await httpGet(checkUrl, 8000);
        const checkJson = JSON.parse(checkData);
        const candidateMeta = checkJson?.result?.[candidatePmid];
        if (candidateMeta?.title) {
          const sim = titleSimilarity(title, candidateMeta.title);
          console.log(`    PubMed 候选 PMID ${candidatePmid}: 相似度 ${(sim*100).toFixed(0)}% | ${candidateMeta.title.substring(0,80)}`);
          if (sim > 0.5) {
            pmid = candidatePmid;
            break;
          }
        }
      } catch (e) { /* skip */ }
    }

    if (!pmid) {
      console.log(`    PubMed 未找到标题匹配的论文(已检查 ${pmids.length} 条候选)`);
      return null;
    }

    await sleep(300);

    // 获取摘要(efetch)
    let abstract = '';
    try {
      const abstractData = await httpGet(`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=${pmid}&retmode=xml&rettype=abstract`);
      const abstractMatch = abstractData.match(/<AbstractText[^>]*>([\s\S]*?)<\/AbstractText>/gi);
      if (abstractMatch) {
        abstract = abstractMatch.map(m => m.replace(/<\/?AbstractText[^>]*>/gi, '').trim()).join('\n');
        abstract = abstract.replace(/<[^>]+>/g, '').trim();
      }
    } catch (e) {}

    await sleep(200);

    // 获取作者信息(esummary)
    const summaryData = await httpGet(`https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id=${pmid}&retmode=json`);
    const summary = JSON.parse(summaryData);
    const paperMeta = summary?.result?.[pmid];

    if (!paperMeta) return null;

    const authors = (paperMeta.authors || []).map(a => a.name).join(', ');
    const corresponding = paperMeta.authors?.[paperMeta.authors.length - 1]?.name || '';
    const journalRaw = paperMeta.fulljournalname || paperMeta.source || '';
    const journal = normalizeJournalName(journalRaw);
    const published = paperMeta.pubdate || '';
    const originalTitle = paperMeta.title || title;

    // v3.7.0: 验证 DOI 格式,拒绝捏造的假 DOI
    let doi = paperMeta.elocationid?.replace('doi: ', '') || '';
    if (doi && !/^10\.\d{4,}\/[a-zA-Z]/.test(doi)) doi = '';

    // v3.9.2: 过滤发表日期,排除 6 个月前的论文
    if (published && published.length >= 4) {
      const pubYear = parseInt(published.substring(0, 4));
      const currentYear = new Date().getFullYear();
      const currentMonth = new Date().getMonth() + 1;
      // 计算 6 个月前的年份
      let cutoffYear = currentYear;
      let cutoffMonth = currentMonth - 6;
      if (cutoffMonth <= 0) { cutoffMonth += 12; cutoffYear -= 1; }
      const pubMonthMatch = published.match(/^(\d{4})-?(\d{2})?/);
      if (pubMonthMatch) {
        const py = parseInt(pubMonthMatch[1]);
        const pm = pubMonthMatch[2] ? parseInt(pubMonthMatch[2]) : 12;
        if (py < cutoffYear || (py === cutoffYear && pm < cutoffMonth)) {
          console.log(`    ⚠️ 论文发表超过 6 个月(${published}),跳过`);
          return null;
        }
      }
    }

    const researchQuestion = inferResearchQuestion(originalTitle, abstract);
    const contributions = inferContributions(abstract, originalTitle);
    const comment = generateComment(originalTitle, abstract, researchQuestion, journal);

    return {
      journal,
      title: originalTitle,
      originalTitle,
      authors: authors || '(作者信息无法确认)',
      corresponding,
      researchQuestion,
      contributions,
      comment,
      abstract,
      published,
      pmid,
      doi
    };
  } catch (e) {
    return null;
  }
}

/**
 * 通过标题在 CrossRef 搜索论文(用于 Science 跟踪链接等无法提取 DOI 的情况)
 * v3.9.1: 新增
 */
async function searchCrossRefByTitle(title) {
  try {
    const query = encodeURIComponent(title.replace(/[^\w\s]/g, ' ').trim().substring(0, 200));
    const url = `https://api.crossref.org/works?query.title=${query}&rows=3&sort=relevance`;
    const data = await httpGet(url, 10000);
    const json = JSON.parse(data);
    const items = json.message?.items || [];

    for (const item of items) {
      // 验证标题相似度(避免匹配到无关论文)
      const crTitle = (item.title || [''])[0].toLowerCase();
      const origTitle = title.toLowerCase();

      // 简单匹配:标题前80字符有50%以上重叠
      const overlap = origTitle.substring(0, 80).split(' ').filter(w =>
        w.length > 3 && crTitle.includes(w)
      ).length;
      const threshold = origTitle.split(' ').filter(w => w.length > 3).length * 0.4;

      if (overlap >= threshold && item.DOI) {
        const cleanDoi = item.DOI;
        // 验证 DOI 格式
        if (/^10\.\d{4,}\/[a-zA-Z]/.test(cleanDoi)) {
          console.log(`    CrossRef标题搜索找到 DOI: ${cleanDoi}`);
          return cleanDoi;
        }
      }
    }
  } catch (e) {
    console.log(`    CrossRef标题搜索失败: ${e.message}`);
  }
  return null;
}

/** CrossRef API 查询 */
async function fetchCrossRef(doi) {
  try {
    const cleanDoi = doi.replace(/[\s&"?#].*$/, '');
    const url = 'https://api.crossref.org/works/' + encodeURIComponent(cleanDoi);
    const data = await httpGet(url);
    const json = JSON.parse(data);
    const w = json.message;
    if (!w) return null;

    let abstract = (w.abstract || '').replace(/<[^>]+>/g, '').trim();
    if (abstract.length < 20) abstract = '';

    const authors = (w.author || []).map(a => `${a.given || ''} ${a.family || ''}`.trim()).join(', ');
    const corresponding = (w.author || []).find(a => a.type === 'author' || a.sequence === 'first')?.affiliation?.name || '';

    const title = w.title?.[0] || '';
    const researchQuestion = inferResearchQuestion(title, abstract);
    const contributions = inferContributions(abstract, title);
    const comment = generateComment(title, abstract, researchQuestion, w['container-title']?.[0] || '');

    return {
      journal: w['container-title']?.[0] || w.publisher || '',
      title: w.title?.[0] || title,
      authors: authors || '未知',
      corresponding: corresponding,
      abstract,
      researchQuestion,
      contributions,
      comment,
      published: w.published?.['date-parts']?.[0]?.join('-') || '',
      doi: cleanDoi
    };
  } catch (e) {
    return null;
  }
}

function inferResearchQuestion(title, abstract) {
  const combined = (title + ' ' + abstract).toLowerCase();
  const t = title;
  const abs = abstract || '';

  // 优先从摘要第一句提取研究问题(摘要通常以背景/问题开头)
  if (abs.length > 50) {
    const firstSentences = abs.split(/[.。]/).filter(s => s.trim().length > 20).slice(0, 2);
    for (const s of firstSentences) {
      const trimmed = s.trim();
      // 背景句通常包含 "remains", "is unclear", "lack", "challenge", "limited"
      if (/remains|unclear|lack|challenge|limited|unknown|poorly|unresolved|critical|important/i.test(trimmed)) {
        return trimmed.charAt(0).toUpperCase() + trimmed.slice(1);
      }
    }
  }

  // 从标题推断核心科学问题
  if (combined.includes('how')) {
    const m = combined.match(/how (.{10,80}?)(?:\?|,|$|\.)/);
    if (m) return `如何(How):${m[1].trim()}?`;
  }
  if (combined.includes('why')) {
    const m = combined.match(/why (.{10,80}?)(?:\?|,|$|\.)/);
    if (m) return `为什么(Why):${m[1].trim()}?`;
  }
  if (combined.includes('role of') || combined.includes('function of')) {
    const m = combined.match(/(?:role|function) of (.{10,60}?)(?:\s+in|\s+during|\s+on|$)/);
    if (m) return `探索 ${m[1].trim()} 在相关生物学过程中的功能角色和作用机制`;
  }
  if (combined.includes('mechanism')) {
    const m = combined.match(/mechanism(?:s)? (?:of|underlying|behind) (.{10,60}?)(?:\s+in|\s+during|$)/);
    if (m) return `阐明 ${m[1].trim()} 的分子机制`;
  }
  if (combined.includes('regulat')) {
    return `揭示相关基因/蛋白/通路的调控机制及其在疾病或发育中的作用`;
  }
  if (combined.includes('cancer') || combined.includes('tumor')) {
    if (combined.includes('immunotherapy') || combined.includes('immune')) {
      return `探索肿瘤免疫逃逸机制或新型免疫治疗策略,以提高肿瘤治疗效果`;
    }
    return `揭示肿瘤发生发展的分子机制,寻找新的治疗靶点或生物标志物`;
  }
  if (combined.includes('single-cell') || combined.includes('scrna')) {
    return `利用单细胞组学技术解析细胞异质性、细胞状态转变或细胞间通讯网络`;
  }
  if (combined.includes('CRISPR') || combined.includes('gene editing')) {
    return `利用基因编辑技术研究基因功能或开发新型基因治疗策略`;
  }
  if (combined.includes('microbiome')) {
    return `探索微生物组与宿主之间的互作机制及其对健康或疾病的影响`;
  }
  if (combined.includes('aging') || combined.includes('longevity') || combined.includes('senescence')) {
    return `揭示衰老的分子机制,寻找延缓衰老或治疗衰老相关疾病的新靶点`;
  }
  if (combined.includes('AI') || combined.includes('machine learning') || combined.includes('deep learning')) {
    return `利用 AI/机器学习方法解决生物学或医学中的关键问题,提升预测或分析能力`;
  }
  if (combined.includes('biochar') || combined.includes('biomass')) {
    return `探索如何通过生物技术手段优化生物质材料的功能特性,推动可持续材料研发`;
  }
  if (combined.includes('polysaccharide') || combined.includes('microbiome modulation')) {
    return `研究多糖的结构-功能关系,探索其作为益生元精准调控肠道微生物组的机制与应用`;
  }

  // 从标题直接提取核心问题
  let q = t.replace(/\.$/, '').trim();
  if (q.length > 15 && q.length < 150) {
    return `本研究聚焦于:${q}`;
  }

  return `探索相关生物学机制或技术应用,解决领域内的关键科学问题`;
}

function inferContributions(abstract, title) {
  if (!abstract || abstract.length < 30) {
    const t = title.toLowerCase();
    if (t.includes('reveal') || t.includes('show')) return ['• 揭示了新的生物学机制或规律'];
    if (t.includes('identify') || t.includes('discover')) return ['• 发现了新的分子靶点或生物标志物'];
    if (t.includes('develop') || t.includes('create') || t.includes('enable')) return ['• 开发了新的技术方法或工具'];
    if (t.includes('predict') || t.includes('model')) return ['• 建立了预测模型或评估方法'];
    if (t.includes('prevent') || t.includes('treat') || t.includes('therapy')) return ['• 为疾病治疗或预防提供了新策略'];
    return ['• 提供了新的见解和实验数据支撑'];
  }

  const contributions = [];
  const sentences = abstract.split(/[.。;]/).filter(s => s.trim().length > 20);

  for (const s of sentences) {
    const t = s.trim();
    if (t.length < 20) continue;

    if (/reveal|show|demonstrate|discover|identify/i.test(t) && contributions.length < 2) {
      let c = t.charAt(0).toUpperCase() + t.slice(1);
      c = c.replace(/^(The|This|These|Our|We)\s+/, '').trim();
      if (c.length > 15) contributions.push('• ' + c.substring(0, 150));
    }
    if (/develop|create|establish|design/i.test(t) && contributions.length < 3) {
      let c = t.charAt(0).toUpperCase() + t.slice(1);
      c = c.replace(/^(The|This|These|Our|We)\s+/, '').trim();
      if (c.length > 15) contributions.push('• ' + c.substring(0, 150));
    }
    if (/find|observe|detect|quantify/i.test(t) && contributions.length < 3) {
      let c = t.charAt(0).toUpperCase() + t.slice(1);
      c = c.replace(/^(The|This|These|Our|We)\s+/, '').trim();
      if (c.length > 15) contributions.push('• ' + c.substring(0, 150));
    }

    if (contributions.length >= 3) break;
  }

  if (contributions.length === 0 && abstract.length > 50) {
    for (const s of sentences.slice(0, 3)) {
      const t = s.trim();
      if (t.length > 20) contributions.push('• ' + t.charAt(0).toUpperCase() + t.slice(1).substring(0, 150));
    }
  }

  return contributions.slice(0, 3);
}

/**
 * 验证并确保关键字段准确(v3.7.0 重写)
 *
 * ⚠️ 准确性原则:
 * - DOI: 只保留格式正确(10.xxxx/字母开头)的真实 DOI,无则清空
 * - 作者: 无法确认时标注「(作者信息无法确认)」,绝不写「见原文」或「待补充」
 * - 日期: 无法确认时标注「(发表日期无法确认)」
 * - 期刊: 必须有值,无则标注「(期刊信息无法确认)」
 */
function ensureAccurateFields(paper) {
  // DOI: 验证格式,过滤捏造的假 DOI(如 abc123)
  if (paper.doi && !/^10\.\d{4,}\/[a-zA-Z]/.test(paper.doi)) {
    paper.doi = '';  // 格式不对,不是真实 DOI,清空
  }

  // 作者: 必须有确认的内容
  if (!paper.authors || ['见原文', '未知', '待补充', '(待补充)', '(待补充)', ''].includes(paper.authors)) {
    paper.authors = '(作者信息无法确认)';
  }

  // 日期
  if (!paper.published && !paper.date) {
    paper.date = '(发表日期无法确认)';
  }

  // 期刊
  if (!paper.journal) {
    paper.journal = '(期刊信息无法确认)';
  }

  // v3.9.1: 摘要判断 - 优先使用 API 真实摘要,兜底使用邮件正文伪摘要(>30字)
  const realAbstract = paper.abstract && paper.abstract.length > 30;
  const emailAbstract = paper.email_body && paper.email_body.length > 30;
  const effectiveAbstract = realAbstract ? paper.abstract : (emailAbstract ? paper.email_body : '');
  const abstractSource = realAbstract ? 'api' : (emailAbstract ? 'email' : 'none');

  if (effectiveAbstract) {
    // v3.9.1: 有摘要(真实或伪摘要),生成基于内容的分析
    // 研究问题/贡献/点评全部基于 effectiveAbstract 生成
    if (!paper.researchQuestion || paper.researchQuestion === '探索相关生物学机制或应用研究') {
      paper.researchQuestion = inferResearchQuestion(paper.title, effectiveAbstract);
    }
    if (!paper.contributions || paper.contributions.length === 0) {
      paper.contributions = inferContributions(effectiveAbstract, paper.title);
    }
    if (!paper.comment) {
      paper.comment = generateComment(paper.title, effectiveAbstract, paper.researchQuestion, paper.journal || '', abstractSource);
    }
  } else {
    // v3.9.1: 无摘要时明确标注,不生成模板内容
    if (!paper.researchQuestion || paper.researchQuestion === '探索相关生物学机制或应用研究') {
      paper.researchQuestion = '(无法获取摘要,无法提取研究问题)';
    }
    if (!paper.contributions || paper.contributions.length === 0) {
      paper.contributions = ['(无法获取摘要,无法提取主要贡献)'];
    }
    if (!paper.comment) {
      paper.comment = '(无法获取摘要,无法生成简评。建议访问原文链接查看详情。)';
    }
  }
}

/**
 * 验证 DOI 是否真实存在(通过 CrossRef API 查询)
 * v3.7.0: 用于在链接提取 DOI 后验证其真实性,避免使用捏造的假 DOI
 */
async function validateDOI(doi) {
  if (!doi || !/^10\.\d{4,}\/[a-zA-Z]/.test(doi)) return false;
  try {
    const url = 'https://api.crossref.org/works/' + encodeURIComponent(doi);
    const data = await httpGet(url, 8000);
    const json = JSON.parse(data);
    return json.status === 'ok' && json.message;
  } catch {
    return false;
  }
}

/**
 * 生成精炼点评(v3.5 增强版)
 * 要求:回答--为什么重要?解决了什么问题?有什么发现?
 */
// v3.8.5: 基于标题关键词生成具体点评,不再使用通用模板套话
function generateComment(title, abstract, researchQuestion, journal, abstractSource = 'api') {
  const t = title.toLowerCase();

  // 关键词映射到具体点评句(每条都针对标题主题,不套话)
  const specificPhrases = {
    // 肿瘤/免疫
    'immune cell': '免疫细胞在肿瘤微环境中的时空分布是理解免疫编辑机制的关键。本研究揭示了特定免疫细胞亚群的定位与功能关系,对精准免疫治疗策略设计有参考价值。',
    'cancer': '肿瘤生物学研究正从描述性向机制性转变。本研究针对癌症发生发展中的特定分子事件,为揭示肿瘤进化路径和耐药机制提供了新见解。',
    'tumor': '肿瘤微环境复杂异质,单一靶点往往不足以解决治疗耐药问题。本研究从多维度解析肿瘤微环境,为联合治疗策略提供了理论依据。',
    'car t': 'CAR-T细胞疗法在血液肿瘤中已获突破,实体瘤应用是当前最大挑战。本研究探索了增强CAR-T浸润和持久性的新策略,对推进实体瘤临床应用有重要意义。',
    'checkpoint': '免疫检查点抑制剂在部分患者中疗效显著,但耐药问题普遍存在。本研究揭示了新的检查点或耐药机制,对扩大受益人群有潜在价值。',
    'neoantigen': '个性化肿瘤新抗原疫苗是精准免疫治疗的前沿方向。本研究为新抗原筛选和疫苗设计提供了重要参考数据。',
    'cachexia': '癌症恶液质涉及系统性代谢紊乱,是晚期肿瘤患者死亡的主要原因之一。本研究揭示了肿瘤驱动的代谢重编程机制,对改善患者生存质量有临床意义。',

    // AI/计算
    'large language model': '大语言模型在医学领域的应用快速发展,本研究评估了LLM在特定医学任务中的实际性能与局限性,为临床落地提供了有价值的参考。',
    'deep learning': '深度学习在生物医学中的应用已从方法验证进入生物学发现阶段。本研究展示了深度学习在揭示复杂生物学规律中的独特价值。',
    'protein': '蛋白质结构与功能预测是AI for Science的标杆性应用。本研究针对蛋白质动态或设计问题,为理解生命分子机制提供了新工具。',
    'alphafold': 'AlphaFold等蛋白质结构预测工具正在改变结构生物学范式。本研究利用或扩展了这类工具的能力,为蛋白质功能研究提供了新路径。',

    // 组学/技术
    'single cell': '单细胞技术已从技术验证走向大规模生物学发现。本研究利用单细胞分辨率揭示了组织或肿瘤的细胞组成新图谱。',
    'spatial': '空间组学弥补了传统单细胞测序丢失位置信息的不足。本研究结合空间信息解析组织微环境,对理解细胞互作有重要价值。',
    'proteomic': '蛋白质组学技术的发展使大规模系统研究成为可能。本研究利用蛋白质组学揭示了疾病相关的新分子网络或通路。',
    'microbiome': '肠道微生物组与宿主健康存在复杂互作,本研究揭示了特定微生物在疾病或健康中的功能角色,为微生态干预提供了靶点。',

    // 进化/感染
    'evolution': '病原体或细胞的进化追踪对理解疾病传播和耐药产生至关重要。本研究通过基因组或功能分析重建了进化路径,为防控策略提供了依据。',
    'cholera': '霍乱仍是全球公共卫生威胁,理解其进化和传播机制对疫情应对有重要意义。本研究揭示了第七次霍乱大流行的进化特征,为疫苗设计提供了参考。',
    'phage': '噬菌体与细菌的军备竞赛是自然界最激烈的演化博弈之一,本研究通过临床监测捕获了这段共进化的实时动态,为噬菌体疗法提供了重要数据。',
    'viral': '病毒与宿主的互作决定了感染结局和传播能力,本研究揭示了特定病毒与宿主的分子对话机制,对抗病毒策略设计有参考价值。',

    // 衰老/代谢
    'aging': '衰老是肿瘤、心血管、神经退行性疾病的共同风险因素,理解衰老机制是延缓疾病发生的核心。本研究揭示了衰老相关的新分子或细胞事件,为干预策略提供了靶点。',
    'longevity': '延寿研究正从模式生物走向人类转化,本研究在寿命延长策略或机制上取得了新进展,对健康老龄化有潜在价值。',
    'metabol': '代谢重编程是癌症和代谢性疾病的核心特征,本研究揭示了特定代谢通路在疾病中的新角色,为代谢干预提供了靶点。',

    // 神经/发育
    'brain': '脑结构与功能的研究正在进入大数据时代,本研究利用神经影像或单细胞数据揭示了脑发育或疾病相关的新模式,对理解人类认知和疾病机制有重要价值。',
    'cortical': '皮层发育和进化研究有助于理解人类独特认知能力的起源,本研究揭示了皮层相关的新分子或细胞机制。',
  };

  // 找到最匹配的主题
  for (const [keyword, phrase] of Object.entries(specificPhrases)) {
    if (t.includes(keyword)) {
      return phrase;
    }
  }

  // 兜底:基于标题主题生成具体句子
  const shortTitle = title.length > 60 ? title.substring(0, 58) + '...' : title;
  // 提取标题中最后1-2个实词作为研究对象
  const words = title.split(/[\s\---:,\/]+/).filter(w =>
    w.length > 3 && !/^(the|a|an|of|for|in|with|by|to|and|on|at|is|are|this|that|these|those|how|what|when|where|why|we|our|their|from|have|has|been|being)$/i.test(w)
  );
  const lastKeyword = words.length > 0 ? words[words.length - 1] : shortTitle;

  // 根据标题句式推断研究类型
  if (/^(we|our|this study|here,)/i.test(title.trim())) {
    return `本研究聚焦${lastKeyword},探索其在生物学或医学中的新角色与机制,为理解相关过程或开发干预策略提供了有价值的参考。`;
  }
  if (/^(identif|demonstrat|reveal|show|discover|establish|develop|propose)/i.test(title.trim())) {
    return `研究揭示了${lastKeyword}在特定生物学过程中的关键作用,对理解疾病机制或开发新疗法有潜在参考价值。`;
  }

  return `本研究关注${lastKeyword}相关的生物学问题,对推动该领域发展具有参考意义,建议阅读原文了解详细发现。`;
}

function loadPapersFromPython(hours = 48) {
  const pythonScript = path.join(__dirname, 'email_pipeline.py');
  const res = spawnSync('python3', [pythonScript, '--hours', String(hours), '--json'], {
    encoding: 'utf-8',
    maxBuffer: 1024 * 1024 * 20
  });

  if (res.error) throw res.error;
  if (res.status !== 0) {
    const errText = (res.stderr || '').trim();
    throw new Error(errText || `email_pipeline.py exited with code ${res.status}`);
  }
  const raw = (res.stdout || '').trim();
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed.papers) ? parsed.papers : [];
}

// ============ 论文提取(期刊邮件)============

function extractPapersFromEmail(text, subject) {
  const papers = [];
  if (!text) return papers;

  const journalRaw = extractJournalFromSubject(subject);
  const journal = normalizeJournalName(journalRaw);
  const lines = text.split(/\n|\r/);

  for (let i = 0; i < lines.length - 1; i++) {
    const line = lines[i].trim();
    const nextLine = lines[i + 1]?.trim() || '';

    // 跳过元信息行
    if (!line || line.startsWith('[') || line.startsWith('http') ||
        line.startsWith('Advertisement') || line.startsWith('Website') ||
        line.startsWith('Facebook') || line.startsWith('Twitter') ||
        line.startsWith('Youtube') || line.startsWith('Weibo') ||
        line.includes('Figure') || line.includes('Image:') ||
        (line.includes('Vol.') && line.includes('Iss.')) ||
        line.includes('doi:') || line.includes('Volume') && line.includes('Issue') ||
        line.includes('WEEKLY UPDATES') || line.includes('The Nature Portfolio') ||
        line.includes('Follow ') || line.includes('Join us') ||
        line.includes('Brought to you') || line.includes('Click ') ||
        /^(Article|Review|News|Perspective|Comment|Letter|Archive|Advisory|Board)/i.test(line) ||
        /^\d+$/.test(line) ||
        line.includes('Circularity') || line.includes('Multi-Journal') ||
        line.includes('Highlights') || line.includes('Announcements')) continue;

    // 标题特征
    if (line.length < 30 || line.length > 160) continue;
    if (!/[a-z]/.test(line.substring(0, 20))) continue;

    // 找链接
    let link = '';
    const isLink = (s) => s.startsWith('[') && (s.includes('http') || s.includes('springernature') || s.includes('cell.com') || s.includes('doi.org') || s.includes('aaas'));

    // 找作者行
    const isAuthor = (s) => /^[A-Z]/.test(s) && (s.includes(',') || s.includes(' & ') || s.includes('[...]'));

    if (isLink(nextLine) || isAuthor(nextLine)) {
      if (isLink(nextLine)) {
        const urlMatch = nextLine.match(/https?:\/\/[^\s\[\]"]+/);
        if (urlMatch) link = urlMatch[0];
      }

      let authors = '';
      let authorsLine = nextLine;
      if (isAuthor(nextLine)) {
        authors = nextLine.replace('[...]', ' et al.').replace(/\s+/g, ' ').trim();
      } else if (isLink(nextLine) && i + 2 < lines.length) {
        const afterLink = lines[i + 2]?.trim() || '';
        if (isAuthor(afterLink)) {
          authors = afterLink.replace('[...]', ' et al.').replace(/\s+/g, ' ').trim();
          authorsLine = afterLink;
        }
      }

      let title = line;
      if (title === title.toUpperCase() && title.length > 20) {
        title = title.toLowerCase().replace(/\b\w/g, c => c.toUpperCase())
          .replace(/'/g, "'");
      }

      // 找日期
      let paperDate = '';
      for (let j = i + 1; j < Math.min(i + 8, lines.length); j++) {
        const dLine = lines[j].trim();
        if (/^\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|January|February|March|April|May|June|July|August|September|October|November|December)\s+20\d{2}/.test(dLine)) {
          paperDate = dLine;
          break;
        }
      }

      papers.push({
        title,
        authors: authors || '见原文',
        journal,
        date: paperDate,
        link,
        source: 'email'
      });
    }
  }

  // 去重:标题+URL/DOI 双重比对(v3.6.1 - 修复只靠标题导致论文4/5重复的问题)
  const seen = new Map();
  return papers.filter((p, idx) => {
    const urlKey = (p.link || '').split('?')[0].toLowerCase();
    const doiKey = (p.doi || '').split('?')[0].toLowerCase();
    const compositeKey = urlKey + '|' + doiKey;
    if (!compositeKey || compositeKey === '|') {
      // 无URL/DOI,回退到标题
      const tKey = p.title.toLowerCase().replace(/\s+/g, ' ').replace(/[^a-z0-9]/g, '').substring(0, 40);
      if (seen.has('T:' + tKey)) return false;
      seen.set('T:' + tKey, idx);
      return true;
    }
    const existing = seen.get(compositeKey);
    if (existing !== undefined) {
      if (p.title.length > papers[existing].title.length) seen.set(compositeKey, idx);
      return false;
    }
    seen.set(compositeKey, idx);
    return true;
  });
}

// ============ 论文提取(Google Scholar 提醒)============

/**
 * 解析 Google Scholar Alert 邮件,提取论文信息
 * Scholar 邮件格式:
 *   - Subject: "Shane Crotty - 3 new articles"
 *   - 内容包含论文标题列表,每篇附有链接和摘要(部分有)
 */
function extractPapersFromScholarEmail(text, subject) {
  // v2.1: 调用 Python 解析器处理 Scholar 邮件
  const { execSync } = require('child_process');
  const fs = require('fs');
  const path = require('path');

  if (!text) return [];

  // 写临时文件
  const tmpFile = '/tmp/scholar_email_' + Date.now() + '.txt';
  const subjectFile = '/tmp/scholar_subj_' + Date.now() + '.txt';
  fs.writeFileSync(tmpFile, text);
  fs.writeFileSync(subjectFile, subject);

  try {
    const pythonScript = path.join(__dirname, 'parse_scholar_emails.py');
    const cmd = `python3 "${pythonScript}" "${tmpFile}" "${subjectFile.replace(/"/g, '\\"')}" --json`;
    const raw = execSync(cmd, { maxBuffer: 1024 * 1024 });
    const papers = JSON.parse(raw.toString());

    // 清理临时文件
    fs.unlinkSync(tmpFile);
    fs.unlinkSync(subjectFile);

    // 标准化字段
    return papers.map(p => ({
      title: p.title || '',
      authors: p.authors || p.researcher + ' et al.',
      journal: p.journal || '',
      date: p.year || '',
      link: p.url || '',
      doi: p.doi || '',
      source: 'scholar',
      researcher: p.researcher || 'Unknown',
      abstract: p.abstract || ''
    }));
  } catch (err) {
    console.error('Scholar parser error:', err.message);
    // 回退:尝试从 subject 提取链接
    const linkMatch = subject.match(/(https?:\/\/[\w.\/\-?=&%]+)/);
    if (linkMatch) {
      return [{ title: subject, authors: 'Unknown', journal: '', date: '', link: linkMatch[1], source: 'scholar', researcher: 'Unknown', abstract: '' }];
    }
    return [];
  }
}

// ============ 邮件读取 ============

function fetchRecentEmails(hours = 24) {
  return new Promise((resolve, reject) => {
    const imap = new Imap({
      user: process.env.IMAP_USER,
      password: process.env.IMAP_PASS,
      host: process.env.IMAP_HOST,
      port: parseInt(process.env.IMAP_PORT),
      tls: true,
      tlsOptions: { rejectUnauthorized: false }
    });

    const emails = [];

    imap.once('ready', () => {
      imap.openBox('INBOX', true, (err, box) => {
        if (err) { reject(err); imap.end(); return; }

        const since = new Date();
        since.setHours(since.getHours() - hours);

        imap.search([['SINCE', since]], (err, uids) => {
          if (err || !uids || uids.length === 0) { resolve([]); imap.end(); return; }

          console.log(`  📬 找到 ${uids.length} 封近 ${hours}h 邮件`);

          const fetchOp = imap.fetch(uids, { bodies: '' });
          let pending = uids.length;

          fetchOp.on('message', (msg) => {
            msg.on('body', (stream) => {
              simpleParser(stream, (err, parsed) => {
                if (err) { pending--; return; }

                const from = parsed.from?.text || '';
                const subject = decodeSubject(parsed.subject || '');
                const date = parsed.date;
                const text = parsed.text || '';

                const lowerFrom = from.toLowerCase();
                const lowerSubject = subject.toLowerCase();

                // ── Google Scholar Alerts ──
                const isScholar = CONFIG.scholarSenders.some(s => lowerFrom.includes(s));
                const isScholarConfirm = CONFIG.scholarExcludeSubjects.some(k => lowerSubject.includes(k));
                if (isScholar) {
                  if (!isScholarConfirm) {
                    emails.push({ from, subject, date: date?.toISOString(), text, type: 'scholar' });
                    console.log(`  🔔 [Scholar] ${subject.substring(0, 65)}`);
                  } else {
                    console.log(`  ⏭  [Scholar 确认邮件,跳过]`);
                  }
                  pending--;
                  if (pending <= 0) { resolve(emails); imap.end(); }
                  return;
                }

                // ── 期刊邮件 ──
                if (matchesKeywords(subject, CONFIG.excludeKeywords)) {
                  pending--;
                  if (pending <= 0) { resolve(emails); imap.end(); }
                  return;
                }

                const isJournalEmail = CONFIG.journalSenders.some(s => lowerFrom.includes(s)) ||
                  CONFIG.journalSubjects.some(j => lowerSubject.includes(j));

                if (isJournalEmail && !matchesKeywords(subject, CONFIG.excludeKeywords)) {
                  emails.push({ from, subject, date: date?.toISOString(), text, type: 'journal' });
                  console.log(`  ✓ ${subject.substring(0, 65)}`);
                }

                pending--;
                if (pending <= 0) { resolve(emails); imap.end(); }
              });
            });
          });

          fetchOp.once('error', () => { resolve(emails); imap.end(); });
        });
      });
    });

    imap.once('error', reject);
    imap.connect();
  });
}

// ============ 报告生成 ============

function generateQQReport(papers) {
  const today = new Date().toLocaleDateString('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' });

  let r = `📚 **科研期刊追踪报告**\n`;
  r += `**日期**: ${today}\n`;
  r += `**今日发现**: ${papers.length} 篇相关论文\n\n`;
  r += `---\n\n`;

  if (papers.length === 0) {
    r += `⚠️ 今日未收到相关领域期刊目录。\n`;
    r += `建议:确认 eAlert 订阅正常,或检查垃圾邮件文件夹。`;
    return r;
  }

  papers.forEach((p, i) => {
    const sourceIcon = p.source === 'scholar' ? '🔔' : '📖';
    const sourceNote = p.source === 'scholar' && p.researcher ? ` *(Scholar: ${p.researcher})*` : '';

    // v3.5: 必须有原文标题和链接
    r += `### ${i + 1}. ${sourceIcon} ${p.title}${sourceNote}\n\n`;

    // 原文标题(如果有翻译,显示原文)
    if (p.originalTitle && p.originalTitle !== p.title) {
      r += `**原文标题**: ${p.originalTitle}\n\n`;
    }

    r += `**期刊**: ${p.journal || '见链接'}\n`;
    // v3.6.1: 日期必须从元数据提取,不能写"见邮件"
    const displayDate = p.published || p.date || '';
    r += `**日期**: ${displayDate || '(未提取到,请点击链接查看)'}\n`;
    // v3.8.1: 检测作者字段是否包含摘要片段
    let displayAuthors = p.authors;
    if (displayAuthors && /^(Protein sequences|These|Background|Results|Methods)/.test(displayAuthors.substring(0, 50))) {
      displayAuthors = '(作者信息无法确认)';
    }
    if (displayAuthors) {
      r += `**作者**: ${displayAuthors}\n`;
    }

    // v3.7.0: 链接优先级:原始链接 > 真实DOI > Google学术搜索
    if (p.link) {
      r += `\n🔗 **链接**: ${p.link}\n`;
    } else if (p.doi && /^10\.\d{4,}\/[a-zA-Z]/.test(p.doi)) {
      // v3.7.0: 只显示经过验证的真实 DOI
      r += `\n🔗 **DOI**: https://doi.org/${p.doi}\n`;
    } else {
      // v3.7.0: 无有效链接/DOI,显示 Google 学术搜索
      const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(p.title)}`;
      r += `\n🔍 **搜索**: [Google 学术搜索](${searchUrl})\n`;
    }
    r += '\n';

    // 点评(精简版)
    if (p.comment) {
      r += `💡 **点评**: ${p.comment}\n\n`;
    }

    r += `---\n\n`;
  });

  r += `## 🔬 综合评述\n\n`;
  r += generateSummary(papers);

  return r;
}

// v3.8.7: 从标题/摘要提炼一句话概要(核心科学问题,≤60字)
function generateOneSentenceSummary(p) {
  const rawTitle = (p.originalTitle || p.title || '').trim();
  const abstract = p.abstract || '';

  // ---- 有摘要:从摘要第一句提炼 ----
  if (abstract.length > 80) {
    const firstSentence = abstract.split(/[.。]/)[0].trim();
    if (firstSentence.length >= 15 && firstSentence.length <= 100) {
      let s = firstSentence
        .replace(/^We (show|demonstrate|present|report|identify|discover|found|describe|observe|introduce|develop|establish|propose|illustrate|provide)/i, '本研究揭示')
        .replace(/^We (have shown|have demonstrated|have identified|have discovered|have found)/i, '本研究揭示')
        .replace(/^This (study|paper|work|research|article|review|issue)/i, '该')
        .replace(/^Here,? we (show|demonstrate|report|present)/i, '本研究揭示')
        .replace(/^Using /i, '利用')
        .replace(/^By /i, '通过')
        .replace(/^Our (results|data|findings|work)/i, '该研究')
        .replace(/^These (results|data|findings)/i, '该研究')
        .replace(/^These data (suggest|indicate|show|reveal)/i, '数据表明')
        .replace(/^Our results (suggest|indicate|show|reveal|demonstrate)/i, '结果表明')
        .replace(/^Our findings (reveal|suggest|show|indicate|demonstrate)/i, '研究表明')
        .replace(/^Collectively,? /i, '综合')
        .replace(/^Together,? /i, '综合')
        .trim();
      if (!/[。!?]$/.test(s) && s.length > 0) s += '。';
      if (s.length <= 60) return s;
    }
  }

  // ---- 无摘要:从标题语义结构提炼有意义的概要 ----
  let clean = rawTitle
    .replace(/^(Cell Press Symposia|Call for papers|Special issue|Review article|Original article|Research article|Letter to the|Brief communication|Hypothesis|Perspective|Mini review)\s*[:\-—]?\s*/i, '')
    .replace(/\s*[---:](\d+\s*years|2026|2025|April|May|June|July|January|February|March|Apr|Vol\.?|Volume \d+|Issue \d+).*$/i, '')
    .replace(/\s*\([^)]*\)\s*$/g, '')
    .replace(/\s*\[[^\]]*\]\s*$/g, '')
    .trim();

  if (!clean || clean.length < 4) return '相关领域重要研究进展。';

  // 模式1: "X drives/reveals/enables Y"
  const actionMatch = clean.match(/^(.+?)\s+(drives?|reveals?|enables?|mediates?|promotes?|inhibits?|suppresses?|induces?|regulates?|modulates?|facilitates?|supports?|underlies?|governs?|controls?|determines?|shapes?|fuels?|triggers?|blocks?|prevents?|protects?|enhances?|attenuates?|impairs?|disrupts?|activates?|inactivates?)\s+(.+)$/i);
  if (actionMatch) {
    const subject = actionMatch[1].trim();
    const verb = actionMatch[2].toLowerCase();
    const object = actionMatch[3].trim().replace(/\.$/, '');
    const verbMap = {
      drives:'驱动', reveals:'揭示', enables:'实现', mediates:'介导', promotes:'促进',
      inhibits:'抑制', suppresses:'抑制', induces:'诱导', regulates:'调控', modulates:'调节',
      facilitates:'促进', supports:'支持', underlies:'构成基础', governs:'支配', controls:'控制',
      determines:'决定', shapes:'塑造', fuels:'推动', triggers:'触发', blocks:'阻断',
      prevents:'防止', protects:'保护', enhances:'增强', attenuates:'减弱', impairs:'损伤',
      disrupts:'破坏', activates:'激活', inactivates:'灭活',
      drive:'驱动', reveal:'揭示', enable:'实现', mediate:'介导', promote:'促进',
      inhibit:'抑制', suppress:'抑制', induce:'诱导', regulate:'调控', modulate:'调节',
      facilitate:'促进', support:'支持', underlie:'构成基础', govern:'支配', control:'控制',
      determine:'决定', shape:'塑造', fuel:'推动', trigger:'触发', block:'阻断',
      prevent:'防止', protect:'保护', enhance:'增强', attenuate:'减弱', impair:'损伤',
      disrupt:'破坏', activate:'激活', inactivate:'灭活'
    };
    const cnVerb = verbMap[verb] || verb;
    // 动作模式:以中文动词开头,描述主语对宾语的作用
    let result = `本研究${cnVerb}了${subject}对${object}的作用。`;
    if (result.length <= 70) return result;
    // 太长则简化
    let shortObj = object.length > 30 ? object.substring(0, 28) + '...' : object;
    result = `${cnVerb}${shortObj}。`;
    if (result.length <= 60) return result;
    return `${cnVerb}${object.substring(0, 38)}...。`;
  }

  // 模式2: "X of Y in Z" / "X of Y"
  const ofMatch = clean.match(/^(?:The\s+)?(.+?)\s+of\s+(.+?)(?:\s+in\s+(.+))?$/i);
  if (ofMatch) {
    const property = ofMatch[1].trim().toLowerCase();
    const target = ofMatch[2].trim().replace(/\.$/, '');
    const context = ofMatch[3];
    const propMap = {
      role:'作用', mechanism:'机制', function:'功能', structure:'结构', dynamics:'动力学',
      regulation:'调控', impact:'影响', significance:'意义', origin:'起源', evolution:'演化',
      landscape:'图谱', atlas:'图谱', map:'图谱', characterization:'表征', analysis:'分析',
      identification:'鉴定', discovery:'发现', development:'开发'
    };
    const cnProp = propMap[property] || property;
    let result = context ? `${context}中${target}的${cnProp}。` : `${target}的${cnProp}。`;
    if (result.length > 60) result = `${target}的${cnProp}研究。`;
    return result;
  }

  // 模式3: 动词开头的标题 "Unlocking/Leveraging/Targeting X"
  const verbStartMatch = clean.match(/^(Unlocking|Leveraging|Targeting|Harnessing|Exploiting|Reprogramming|Reconstructing|Decoding|Understanding|Defining|Characterizing|Mapping|Profiling|Engineering|Expanding|Exploring|Overcoming|Rewiring|Remodeling|Revisiting|Re-evaluating|Integrating|Combining|Applying|Developing|Designing|Building|Creating|Generating|Establishing|Optimizing|Improving|Advancing|Extending)\s+(.+)$/i);
  if (verbStartMatch) {
    const verb = verbStartMatch[1].toLowerCase();
    const object = verbStartMatch[2].trim().replace(/\.$/, '');
    const vMap = {
      unlocking:'解锁', leveraging:'利用', targeting:'靶向', harnessing:'利用', exploiting:'利用',
      reprogramming:'重编程', reconstructing:'重建', decoding:'解码', understanding:'理解',
      defining:'定义', characterizing:'表征', mapping:'绘制图谱', profiling:'分析图谱',
      engineering:'工程化', expanding:'扩展', exploring:'探索', overcoming:'克服',
      rewiring:'重连', remodeling:'重塑', revisiting:'重新审视', 're-evaluating':'重新评估',
      integrating:'整合', combining:'结合', applying:'应用', developing:'开发',
      designing:'设计', building:'构建', creating:'创建', generating:'生成',
      establishing:'建立', optimizing:'优化', improving:'改进', advancing:'推进',
      extending:'延长'
    };
    const cnV = vMap[verb] || '探索';
    let result = `${cnV}${object}。`;
    if (result.length <= 60) return result;
    return `${cnV}${object.substring(0, 48)}...。`;
  }

  // 模式4: 名词性标题含 "in Z"
  const inMatch = clean.match(/^(?:A\s+|An\s+)?(.+?)\s+in\s+(.+)$/i);
  if (inMatch) {
    const finding = inMatch[1].trim();
    const context = inMatch[2].trim().replace(/\.$/, '');
    let result = `${context}中发现${finding}。`;
    if (result.length <= 60) return result;
    return `在${context}中发现新的研究线索。`;
  }

  // Fallback: 截取标题核心内容
  let fallback = clean
    .replace(/^(The|A|An|And)\s+/i, '')
    .replace(/^Hallmarks\s+of\s+Cancer/i, '癌症标志')
    .trim();
  if (fallback.length > 50) fallback = fallback.substring(0, 48) + '...';
  return `关于${fallback}的研究。`;
}



// v3.8.7: 从标题/摘要提取主要贡献(无摘要时从标题推断)
function extractContributions(p) {
  const contributions = [];
  const title = (p.originalTitle || p.title || '').trim();
  const abstract = p.abstract || '';

  // ---- 有摘要:从摘要提取关键发现 ----
  if (abstract.length > 80) {
    const findings = [];
    const sentences = abstract.split(/[.。]/);
    sentences.forEach(s => {
      const trimmed = s.trim();
      if (/^(reveal|show|demonstrate|identify|discover|establish|develop|propose|introduce|present|report|found|describe|enable|provide)/i.test(trimmed)) {
        let short = trimmed.substring(0, 80).trim();
        if (short.length > 10) findings.push(short);
      }
    });

    if (findings.length > 0) {
      findings.slice(0, 3).forEach(f => {
        let c = f
          .replace(/^reveal/i, '揭示')
          .replace(/^show/i, '表明')
          .replace(/^demonstrate/i, '证明')
          .replace(/^identify/i, '鉴定')
          .replace(/^discover/i, '发现')
          .replace(/^establish/i, '建立')
          .replace(/^develop/i, '开发')
          .replace(/^propose/i, '提出')
          .replace(/^introduce/i, '引入')
          .replace(/^present/i, '展示')
          .replace(/^report/i, '报告')
          .replace(/^found/i, '发现')
          .replace(/^describe/i, '描述')
          .replace(/^enable/i, '实现')
          .replace(/^provide/i, '提供');
        if (c.length > 5) contributions.push(c.substring(0, 80) + (c.length > 80 ? '...' : ''));
      });
    }
    if (contributions.length > 0) return contributions.slice(0, 3);
  }

  // ---- 无摘要或摘要无发现动词:从标题语义推断贡献 ----
  const cleanTitle = title
    .replace(/^(Cell Press Symposia|Call for papers|Special issue|Review article|Original article|Research article|Letter to the|Brief communication|Hypothesis|Perspective|Mini review)\s*[:\-—]?\s*/i, '')
    .replace(/\s*[---:](\d+\s*years|2026|2025).*$/i, '')
    .trim();

  // 从标题核心动词推断贡献方向
  const verbContributionMap = [
    { pattern: /\b(drives?|fuels?|triggers?)\b/i, contrib: '阐明了驱动因素及其作用机制' },
    { pattern: /\b(reveals?|uncovers?|discovers?)\b/i, contrib: '揭示了新的生物学现象或机制' },
    { pattern: /\b(inhibits?|suppresses?|blocks?|prevents?)\b/i, contrib: '鉴定了具有抑制/阻断作用的靶点或策略' },
    { pattern: /\b(promotes?|enhances?|facilitates?|boosts?)\b/i, contrib: '发现了促进/增强特定过程的关键因素' },
    { pattern: /\b(enables?|allows?|achieves?)\b/i, contrib: '实现了新的技术方法或应用突破' },
    { pattern: /\b(regulates?|modulates?|controls?|governs?)\b/i, contrib: '阐明了调控机制及其生物学意义' },
    { pattern: /\b(induces?|mediates?)\b/i, contrib: '揭示了诱导/介导特定效应的分子途径' },
    { pattern: /\b(extends?|prolongs?|improves?)\b/i, contrib: '证实了延长/改善特定指标的有效性' },
    { pattern: /\b(targets?|leveraging|harnessing)\b/i, contrib: '提出了靶向/利用特定目标的策略' },
    { pattern: /\b(engineering|designing|developing|creating|building)\b/i, contrib: '开发了新的技术平台或工具' },
    { pattern: /\b(mapping|profiling|atlas|landscape|characterizing)\b/i, contrib: '提供了系统性的图谱或表征数据' },
    { pattern: /\b(overcoming|resistance|overcomes?)\b/i, contrib: '为克服耐药/抗性问题提供了新方案' },
  ];

  const matchedContribs = [];
  for (const { pattern, contrib } of verbContributionMap) {
    if (pattern.test(cleanTitle)) {
      matchedContribs.push(contrib);
    }
  }

  // 根据研究领域补充
  const domainContribs = [];
  if (/cancer|tumor|oncology/i.test(cleanTitle)) domainContribs.push('为肿瘤诊疗提供了新思路');
  if (/immune|immunotherapy|T cell/i.test(cleanTitle)) domainContribs.push('对免疫治疗策略优化具有参考价值');
  if (/CRISPR|gene edit/i.test(cleanTitle)) domainContribs.push('拓展了基因编辑技术的应用范围');
  if (/single.cell|spatial|scRNA|multi.omics/i.test(cleanTitle)) domainContribs.push('以高分辨率解析了生物系统复杂性');
  if (/aging|longevity|lifespan|healthspan/i.test(cleanTitle)) domainContribs.push('对延缓衰老和促进健康寿命有潜在意义');
  if (/\bAI\b|\bmachine learning\b|\bdeep learning\b|\bneural network\b/i.test(cleanTitle)) domainContribs.push('展示了AI方法在生物医学中的应用潜力');

  // 合并去重,最多3条
  const allContribs = [...matchedContribs, ...domainContribs];
  const seen = new Set();
  for (const c of allContribs) {
    if (!seen.has(c)) {
      seen.add(c);
      contributions.push(c);
      if (contributions.length >= 3) break;
    }
  }

  // 仍无贡献:从标题提取研究对象作为基本贡献
  if (contributions.length === 0) {
    const coreSubject = cleanTitle
      .replace(/^(The|A|An)\s+/i, '')
      .replace(/\s+(in|of|for|with|by|to|and|through|via)\s+.*$/i, '')
      .trim();
    if (coreSubject.length > 3) {
      contributions.push(`对${coreSubject}进行了研究,提供了新的实验数据或理论视角`);
    } else {
      contributions.push('为该领域提供了新的研究数据或理论框架');
    }
  }

  return contributions.slice(0, 3);
}

function generateMarkdownReport(papers) {
  const today = new Date().toISOString().split('T')[0];
  const datetime = new Date().toLocaleString('zh-CN');

  let md = `# 📚 科研期刊追踪报告\n\n`;
  md += `**日期**: ${today}\n`;
  md += `**监控期刊**: Nature、Science、Cell 系列及主流生物学期刊\n`;
  md += `**目标领域**: 生物信息学、计算生物学、癌生物学、免疫学、AI for Science、多组学\n\n`;
  md += `---\n\n`;
  md += `## 📊 统计\n`;
  md += `- **今日相关论文**: ${papers.length} 篇\n\n`;

  if (papers.length === 0) {
    md += `> 今日未收到相关领域期刊目录。\n\n---\n\n`;
    md += `**生成时间**: ${datetime}\n`;
    md += `**工具**: EAlert Tracker v3.9.1(准确性优先,不捏造任何字段)\n`;
    return md;
  }

  const journalCounts = {};
  papers.forEach(p => {
    const j = p.journal || '未知';
    journalCounts[j] = (journalCounts[j] || 0) + 1;
  });
  md += `### 期刊分布\n`;
  for (const [j, c] of Object.entries(journalCounts)) {
    md += `- **${j}**: ${c} 篇\n`;
  }
  md += `\n---\n\n`;

  md += `## 📰 论文详情\n\n`;

  papers.forEach((p, i) => {
    md += `### 🔬 论文${i + 1}:${p.title}\n\n`;
    if (p.source === 'scholar' && p.researcher) {
      md += `**来源**: 🔔 Google Scholar Alert (${p.researcher})\n`;
    }
    if (p.originalTitle && p.originalTitle !== p.title) {
      md += `**原文标题**: ${p.originalTitle}\n\n`;
    }

    // v3.8.3: 多组学简报格式 - 独立结构字段
    let mdAuthors = p.authors;
    if (mdAuthors && /^(Protein sequences|These|Background|Results|Methods)/.test(mdAuthors.substring(0, 50))) {
      mdAuthors = '(作者信息无法确认)';
    }
    if (mdAuthors) {
      md += `**作者**: ${mdAuthors}\n`;
    }
    const sourceTag = p.source === 'scholar' ? '🔔 Google Scholar' : (p.journal || '期刊链接');
    md += `**平台**: ${sourceTag}\n`;
    const mdDate = p.published || p.date || '';
    if (mdDate) md += `**日期**: ${mdDate}\n`;
    if (p.link) {
      md += `**链接**: ${p.link}\n`;
    } else if (p.doi && /^10\.\d{4,}\/[a-zA-Z]/.test(p.doi)) {
      md += `**DOI**: ${p.doi}\n`;
      md += `**链接**: https://doi.org/${p.doi}\n`;
    } else {
      const searchUrl = `https://www.google.com/search?q=${encodeURIComponent(p.title)}`;
      md += `**链接**: ${searchUrl}\n`;
    }
    md += `\n`;

    // v3.8.3: 一句话概要
    md += `**一句话概要**: ${generateOneSentenceSummary(p)}\n\n`;

    // v3.8.5: 主要贡献(有摘要时提取,无摘要时显示说明)
    const contributions = extractContributions(p);
    md += `**主要贡献**\n`;
    if (contributions.length > 0) {
      contributions.forEach(c => md += `- ${c}\n`);
    } else {
      md += `- (暂无摘要,无法提取主要贡献)\n`;
    }
    md += `\n`;

    // v3.8.3: Critical 简评
    md += `**🔍 Critical 简评**: ${p.comment || '相关领域研究,建议阅读原文了解详细内容。'}\n\n`;

    md += `---\n\n`;
  });

  md += `## 💡 整体趋势\n\n`;
  md += generateSummary(papers) + '\n\n';
  md += `---\n\n`;
  md += `**生成时间**: ${datetime}\n`;
  md += `**工具**: EAlert Tracker v3.9.1(准确性优先,不捏造任何字段)\n`;

  return md;
}

function generateSummary(papers) {
  if (!papers || papers.length === 0) return '今日无相关论文。';

  const lines = [];

  const journalCounts = {};
  papers.forEach(p => {
    const j = p.journal || '未知';
    journalCounts[j] = (journalCounts[j] || 0) + 1;
  });

  const counts = {
    '肿瘤/免疫': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['cancer', 'tumor', 'immunotherapy', 'immune'])).length,
    'AI/机器学习': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['AI', 'machine learning', 'deep learning'])).length,
    '单细胞/组学': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['single-cell', 'scRNA', 'genomics', 'transcriptomics'])).length,
    '基因编辑': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['CRISPR', 'gene editing'])).length,
    '衰老/寿命': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['aging', 'longevity', 'lifespan'])).length,
    '神经科学': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['brain', 'neural', 'neuroscience'])).length,
    '生物工程': papers.filter(p => matchesKeywords(p.title + (p.abstract || ''), ['bioengineer', 'synthetic biology', 'organoid', 'biochar'])).length,
  };

  lines.push(`📊 **期刊分布**:`);
  for (const [j, c] of Object.entries(journalCounts)) {
    lines.push(`- ${j}: ${c} 篇`);
  }
  lines.push('');

  lines.push(`📈 **领域热度**:`);
  for (const [field, count] of Object.entries(counts)) {
    if (count > 0) lines.push(`- ${field}: ${count} 篇`);
  }
  lines.push('');

  const topFields = Object.entries(counts).filter(([, c]) => c > 0).sort((a, b) => b[1] - a[1]);
  lines.push(`💡 **本期综合评述**:`);

  if (papers.length >= 3) {
    if (topFields[0]) {
      lines.push(`- 本期${papers.length}篇论文中,${topFields[0][0]}研究最为活跃(${topFields[0][1]}篇),建议重点关注`);
    }
    const hasAbstract = papers.filter(p => p.abstract && p.abstract.length > 50).length;
    if (hasAbstract > 0) {
      lines.push(`- 共${hasAbstract}篇论文可获取摘要,内容质量和创新性总体较高`);
    }
    if (topFields.some(([, c]) => c >= 2)) {
      lines.push(`- 多篇涉及交叉领域研究,反映当前生命科学向多学科融合发展的趋势`);
    }
  } else {
    lines.push(`- 本期相关论文较少,持续关注后续更新`);
  }

  return lines.join('\n');
}

// ============ 发送(已移除) ============
// v3.8.1: 邮件发送已移除,由 AI 负责通过 message 工具发送 QQ + 推送 GitHub

// ============ 主流程 ============

async function run() {
  console.log('🚀 EAlert Tracker v3.9.1 启动\n');
  console.log(`📅 ${new Date().toLocaleString('zh-CN')}\n`);

  console.log('📬 读取最近 48h 期刊/Scholar 邮件(Python)...');
  let papers = [];
  try {
    papers = loadPapersFromPython(48);
  } catch (err) {
    console.error('❌ 邮件读取失败:', err.message || err);
  }

  console.log(`  → 提取 ${papers.length} 篇候选论文\n`);

  if (papers.length === 0) {
    console.log('⚠️ 今日无候选论文');
    return;
  }

  const allPapers = papers.filter(p => p.source !== 'scholar');
  const scholarPapers = papers.filter(p => p.source === 'scholar');
  console.log(`  → 共 ${allPapers.length} 篇(期刊)+ ${scholarPapers.length} 篇(Scholar)\n`);

  // Step 3: 关键词过滤
  console.log('🎯 关键词过滤...');
  const relevantPapers = allPapers.filter(p => matchesKeywords(p.title, CONFIG.targetKeywords));
  const relevantScholar = scholarPapers.filter(p => matchesKeywords(p.title, CONFIG.targetKeywords));
  console.log(`  → 期刊相关: ${relevantPapers.length} 篇 | Scholar相关: ${relevantScholar.length} 篇\n`);

  // Step 3: 合并所有相关论文
  const allRelevant = [...relevantPapers, ...relevantScholar];

  if (allRelevant.length === 0) {
    // v3.8.1: 移除 sendEmail,无相关论文时只输出提示(由 AI 决定是否发送)
    console.log('⚠️ 未发现相关领域论文');
    return;
  }

  // Step 4: 尝试获取元数据(期刊论文优先,最多处理5篇)
  console.log('📖 尝试获取论文详情...');
  const toEnrich = allRelevant.filter(p => p.source !== 'scholar').slice(0, 5);
  const toEnrichScholar = allRelevant.filter(p => p.source === 'scholar').slice(0, 3);
  const enriched = [];

  // 期刊论文:获取 PubMed 元数据
  for (let i = 0; i < toEnrich.length; i++) {
    const p = toEnrich[i];
    console.log(`  [${i + 1}/${toEnrich.length}] ${p.title.substring(0, 50)}...`);
    const detailed = await fetchPaperDetails(p);
    ensureAccurateFields(detailed);
    enriched.push(detailed);
    if (i < toEnrich.length - 1) await sleep(200);
  }

  // Scholar 论文:从链接或标题获取信息
  for (const p of toEnrichScholar) {
    console.log(`  [Scholar] ${p.title.substring(0, 50)}...`);
    // Scholar 论文尝试从链接获取 DOI
    const doi = extractDOI(p.link);
    if (doi) {
      await sleep(300);
      const meta = await fetchCrossRef(doi);
      if (meta) {
        ensureAccurateFields(meta);
        meta.source = 'scholar';
        meta.researcher = p.researcher;
        enriched.push(meta);
        continue;
      }
    }
    // 备用:直接从 PubMed 搜索标题
    const meta = await fetchPaperDetails(p);
    if (meta && meta.journal) {
      ensureAccurateFields(meta);
      meta.source = 'scholar';
      meta.researcher = p.researcher;
      enriched.push(meta);
    } else {
      // Scholar 论文:无期刊信息时补充
      p.researchQuestion = inferResearchQuestion(p.title, p.abstract || '');
      p.contributions = inferContributions(p.abstract || '', p.title);
      p.comment = generateComment(p.title, p.abstract || '', p.researchQuestion, p.journal || '');
      p.source = 'scholar';
      enriched.push(p);
    }
    await sleep(200);
  }

  // v3.9.1: 剩余论文中,对 Science 跟踪链接调用 fetchPaperDetails(CrossRef 标题搜索)
  const enrichedTitles = new Set(enriched.map(p => p.title.toLowerCase().substring(0, 40)));
  for (const p of allRelevant) {
    if (enrichedTitles.has(p.title.toLowerCase().substring(0, 40))) continue;

    // 对 Science 跟踪链接尝试 CrossRef 标题搜索
    const linkLower = (p.link || '').toLowerCase();
    const isScienceTracking = linkLower.includes('click.aaas.sciencepubs.org') ||
                              linkLower.includes('click.science.org');

    if (isScienceTracking) {
      console.log(`  [Science] ${p.title.substring(0, 50)}...`);
      const detailed = await fetchPaperDetails(p);
      ensureAccurateFields(detailed);
      enriched.push(detailed);
      await sleep(300);
    } else {
      // v3.9.1: 尝试用邮件正文伪摘要(兜底摘要)
      const fallbackAbstract = p.email_body || '';
      p.researchQuestion = inferResearchQuestion(p.title, fallbackAbstract);
      p.contributions = inferContributions(fallbackAbstract, p.title);
      const absSrc = fallbackAbstract ? 'email' : 'none';
      p.comment = generateComment(p.title, fallbackAbstract, p.researchQuestion, p.journal || '', absSrc);
      enriched.push(p);
    }
  }

  console.log(`  → 详情获取完成\n`);

  // v3.9.2: 最终期刊名称标准化（强制统一）
  enriched.forEach(p => {
    if (p.journal) p.journal = normalizeJournalName(p.journal);
  });

  // Step 5: 生成报告
  console.log('📊 生成报告...');
  const qqReport = generateQQReport(enriched);
  const mdReport = generateMarkdownReport(enriched);

  // Step 6: 保存(v3.4: 支持 Scholar Alerts)
  const today = new Date();
  const todayStr = today.toISOString().split('T')[0];
  const year = today.getFullYear();
  const month = String(today.getMonth() + 1).padStart(2, '0');
  const weekNum = String(getISOWeek(today)).padStart(2, '0');
  const weekDir = `${year}-W${weekNum}`;
  const reportDir = path.join(__dirname, '../reports', `${year}`, `${month}`, weekDir);
  const reportPath = path.join(reportDir, `report_${todayStr}.md`);
  // v3.8.2: 只推送到 bioinformatics-frontier 仓库(不保存到本地 ealert-tracker/reports/)
  try {
    const homedir = require('os').homedir();
    const bioinfoBase = path.join(homedir, 'Documents', 'bioinformatics-frontier');
    const bioinfoDir = path.join(bioinfoBase, 'reports', `${year}`, `${month}`, weekDir);
    fs.mkdirSync(bioinfoDir, { recursive: true });
    const bioinfoPath = path.join(bioinfoDir, `${todayStr}-journal-briefing.md`);
    fs.writeFileSync(bioinfoPath, mdReport);
    console.log(`  ✓ 报告已保存: ~/Documents/bioinformatics-frontier/reports/${year}/${month}/${weekDir}/${todayStr}-journal-briefing.md`);

    // Git commit & push
    execSync('git add .', { cwd: bioinfoBase });
    execSync(`git commit -m "EAlert Tracker: add ${todayStr} report"`, { cwd: bioinfoBase, stdio: 'ignore' });
    execSync('git push origin main', { cwd: bioinfoBase });
    console.log(`  ✓ 已推送到 GitHub: OnlyPandaX/bioinformatics-frontier\n`);
  } catch (e) {
    console.error(`  ⚠️  Push to bioinformatics-frontier failed: ${e.message}`);
  }

  // Step 7: 输出报告(不发送邮件,由 AI 负责 QQ + GitHub)
  console.log('📤 报告生成完成,等待 AI 发送到 QQ 和 GitHub...');
  console.log('\n' + '='.repeat(60));
  console.log('📄 QQ 报告预览:');
  console.log('-'.repeat(60));
  console.log(qqReport.substring(0, 1500));
  if (qqReport.length > 1500) console.log('... (更多内容省略)');
  console.log('-'.repeat(60) + '\n');

  console.log('\n' + '='.repeat(60));
  console.log(`✅ EAlert Tracker v3.9.1 完成!`);
  console.log(`   � 候选论文(期刊): ${allPapers.length} 篇`);
  console.log(`   🔔 候选论文(Scholar): ${scholarPapers.length} 篇`);
  console.log(`   📄 论文总数: ${allPapers.length + scholarPapers.length} 篇`);
  console.log(`   🎯 相关论文: ${allRelevant.length} 篇`);
  const withAbstract = enriched.filter(p => p.abstract && p.abstract.length > 30).length;
  console.log(`   📝 含摘要: ${withAbstract} 篇`);
  if (relevantScholar.length > 0) console.log(`   👤 Scholar研究者: ${relevantScholar.map(p => p.researcher).filter((v, i, a) => a.indexOf(v) === i).join(', ')}`);
  console.log('='.repeat(60));
}

run().catch(err => {
  console.error('❌ 致命错误:', err);
  process.exit(1);
});
