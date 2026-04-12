import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import SearchPage from './pages/SearchPage';
import SearchByUrlPage from './pages/SearchByUrlPage';
import ProposalsPage from './pages/ProposalsPage';
import BulkSearchPage from './pages/BulkSearchPage';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<SearchPage />} />
        <Route path="/search-url" element={<SearchByUrlPage />} />
        <Route path="/proposals" element={<ProposalsPage />} />
        <Route path="/bulk" element={<BulkSearchPage />} />
      </Route>
    </Routes>
  );
}
